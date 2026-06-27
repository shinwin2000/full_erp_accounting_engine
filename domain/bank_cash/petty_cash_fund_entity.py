#!/usr/bin/env python3
"""
Module: petty_cash_fund_entity.py
Layer: Domain / Bank & Cash
Responsibility: Dana kas kecil dengan replenishment otomatis, disbursement,
               adjustment, audit trail, dan multiple custodian support.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class PettyCashStatus(Enum):
    ACTIVE = "active"
    DEPLETED = "depleted"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    PENDING_APPROVAL = "pending_approval"
    FROZEN = "frozen"
    UNDER_AUDIT = "under_audit"

    @classmethod
    def can_transition(cls, from_status: PettyCashStatus, to_status: PettyCashStatus) -> bool:
        allowed = {
            cls.PENDING_APPROVAL: {cls.ACTIVE, cls.CLOSED},
            cls.ACTIVE: {cls.DEPLETED, cls.SUSPENDED, cls.CLOSED, cls.FROZEN},
            cls.DEPLETED: {cls.ACTIVE, cls.CLOSED},
            cls.SUSPENDED: {cls.ACTIVE, cls.CLOSED, cls.UNDER_AUDIT},
            cls.UNDER_AUDIT: {cls.ACTIVE, cls.CLOSED},
            cls.FROZEN: {cls.ACTIVE, cls.CLOSED},
            cls.CLOSED: set(),
        }
        return to_status in allowed.get(from_status, set())


class PettyCashTransactionType(Enum):
    DISBURSEMENT = "disbursement"
    REPLENISHMENT = "replenishment"
    ADJUSTMENT = "adjustment"
    INITIAL_FUND = "initial_fund"
    CLOSING = "closing"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    REVERSAL = "reversal"
    AUDIT_ADJUSTMENT = "audit_adjustment"


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class PettyCashTransaction:
    """Transaksi individual dalam petty cash."""

    transaction_id: UUID
    transaction_date: datetime
    type: PettyCashTransactionType
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    description: str
    reference: str | None
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    signature: str | None = None

    def __post_init__(self) -> None:
        if not self.signature:
            object.__setattr__(self, "signature", self._calculate_signature())

    def _calculate_signature(self) -> str:
        data = f"{self.transaction_id}{self.amount}{self.balance_after}{self.transaction_date}"
        return hashlib.sha3_256(data.encode()).hexdigest()

    def verify_signature(self) -> bool:
        return self.signature == self._calculate_signature()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "transaction_date": self.transaction_date.isoformat(),
            "type": self.type.value,
            "amount": str(self.amount),
            "balance_before": str(self.balance_before),
            "balance_after": str(self.balance_after),
            "description": self.description,
            "reference": self.reference,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class PettyCashFundSignature:
    """Digital signature for petty cash fund."""

    petty_cash_id: UUID
    version: int
    hash_value: str
    signed_at: datetime
    signed_by: str

    @classmethod
    def create(cls, petty_cash: PettyCashFundEntity, signed_by: str) -> Self:
        data = f"{petty_cash.petty_cash_id}{petty_cash.version}{petty_cash.current_balance}{petty_cash.updated_at}"
        hash_value = hashlib.sha3_256(data.encode()).hexdigest()
        return cls(
            petty_cash_id=petty_cash.petty_cash_id,
            version=petty_cash.version,
            hash_value=hash_value,
            signed_at=datetime.now(UTC),
            signed_by=signed_by,
        )

    def verify(self, petty_cash: PettyCashFundEntity) -> bool:
        data = f"{petty_cash.petty_cash_id}{petty_cash.version}{petty_cash.current_balance}{petty_cash.updated_at}"
        expected = hashlib.sha3_256(data.encode()).hexdigest()
        return self.hash_value == expected


@dataclass
class PettyCashAuditLog:
    """Audit log entry for petty cash."""

    entry_id: UUID
    action: str
    performed_by: str
    performed_at: datetime
    details: dict[str, Any]
    signature: str | None = None

    def __post_init__(self) -> None:
        if not self.signature:
            data = f"{self.entry_id}{self.action}{self.performed_by}{self.performed_at}"
            self.signature = hashlib.sha3_256(data.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "action": self.action,
            "performed_by": self.performed_by,
            "performed_at": self.performed_at.isoformat(),
            "details": self.details,
            "signature": self.signature,
        }


# ============================================================================
# Petty Cash Fund Entity
# ============================================================================


@dataclass
class PettyCashFundEntity:
    petty_cash_id: UUID
    petty_cash_code: str
    petty_cash_name: str
    legal_entity_id: UUID
    currency: str
    initial_fund: Decimal
    current_balance: Decimal
    total_disbursements: Decimal
    replenishment_threshold: Decimal
    replenishment_amount: Decimal
    status: PettyCashStatus
    custodian_name: str
    custodian_employee_id: UUID | None = None
    secondary_custodian_name: str | None = None
    secondary_custodian_employee_id: UUID | None = None
    maximum_disbursement_per_transaction: Decimal = Decimal("0")
    daily_disbursement_limit: Decimal = Decimal("0")
    today_disbursements: Decimal = Decimal("0")
    monthly_disbursement_limit: Decimal = Decimal("0")
    month_disbursements: Decimal = Decimal("0")
    last_replenishment_date: datetime | None = None
    last_audit_date: datetime | None = None
    last_audited_by: str | None = None
    notes: str | None = None
    transactions: list[PettyCashTransaction] = field(default_factory=list)
    audit_logs: list[PettyCashAuditLog] = field(default_factory=list)
    suspended_at: datetime | None = None
    suspended_by: str | None = None
    suspended_reason: str | None = None
    frozen_at: datetime | None = None
    frozen_by: str | None = None
    frozen_reason: str | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    signature: PettyCashFundSignature | None = None

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if not self.petty_cash_code or len(self.petty_cash_code.strip()) < 2:
            raise ValueError("Petty cash code must be at least 2 characters")
        if not self.petty_cash_name or len(self.petty_cash_name.strip()) < 2:
            raise ValueError("Petty cash name must be at least 2 characters")
        self.initial_fund = self.initial_fund.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if self.initial_fund <= 0:
            raise ValueError(f"Initial fund must be positive: {self.initial_fund}")
        self.current_balance = self.current_balance.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        if self.current_balance < 0:
            raise ValueError(f"Petty cash balance cannot be negative: {self.current_balance}")
        self.total_disbursements = self.total_disbursements.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        self.replenishment_threshold = self.replenishment_threshold.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        if self.replenishment_threshold < 0:
            raise ValueError(
                f"Replenishment threshold cannot be negative: {self.replenishment_threshold}"
            )
        self.replenishment_amount = self.replenishment_amount.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        if self.replenishment_amount <= 0:
            raise ValueError(f"Replenishment amount must be positive: {self.replenishment_amount}")
        if not self.custodian_name.strip():
            raise ValueError("Custodian name is required")
        if self.maximum_disbursement_per_transaction < 0:
            raise ValueError("Maximum disbursement per transaction cannot be negative")
        if self.daily_disbursement_limit < 0:
            raise ValueError("Daily disbursement limit cannot be negative")
        if self.monthly_disbursement_limit < 0:
            raise ValueError("Monthly disbursement limit cannot be negative")
        if not PettyCashStatus.can_transition(self.status, self.status):
            if self.status not in PettyCashStatus:
                raise ValueError(f"Invalid status: {self.status}")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = PettyCashAuditLog(
            entry_id=uuid4(),
            action=action,
            performed_by=performed_by,
            performed_at=datetime.now(UTC),
            details=details,
        )
        self._audit_trail.append(entry.to_dict())
        self.audit_logs.append(entry)

    def _calculate_signature(self) -> PettyCashFundSignature:
        return PettyCashFundSignature.create(self, self.created_by)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> Self:
        self._record_audit(
            "CREATE",
            created_by,
            {"code": self.petty_cash_code, "initial_fund": str(self.initial_fund)},
        )
        return self

    def update(self, updated_by: str, **kwargs) -> Self:
        if self.status not in (PettyCashStatus.ACTIVE, PettyCashStatus.PENDING_APPROVAL):
            raise ValueError(f"Cannot update petty cash in status {self.status.value}")

        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "petty_cash_id",
                "created_at",
                "created_by",
                "version",
            ):
                data[key] = value

        new_pc = self.from_dict(data)
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_pc

    def delete(self, deleted_by: str, reason: str | None = None) -> Self:
        if self.current_balance != 0:
            raise ValueError(
                f"Cannot delete petty cash with non-zero balance: {self.current_balance}"
            )

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.CLOSED
        new_pc.closed_at = datetime.now(UTC)
        new_pc.closed_by = deleted_by
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_pc

    def restore(self, restored_by: str) -> Self:
        if self.status != PettyCashStatus.CLOSED:
            raise ValueError(f"Cannot restore petty cash in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.ACTIVE
        new_pc.closed_at = None
        new_pc.closed_by = None
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("RESTORE", restored_by, {})
        return new_pc

    def activate(self, activated_by: str) -> Self:
        if self.status != PettyCashStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot activate petty cash in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.ACTIVE
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("ACTIVATE", activated_by, {})
        return new_pc

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> Self:
        if self.status != PettyCashStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate petty cash in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.SUSPENDED
        new_pc.suspended_at = datetime.now(UTC)
        new_pc.suspended_by = deactivated_by
        new_pc.suspended_reason = reason
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_pc

    def lock(self, locked_by: str, reason: str) -> Self:
        if self.status != PettyCashStatus.ACTIVE:
            raise ValueError(f"Cannot lock petty cash in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.FROZEN
        new_pc.frozen_at = datetime.now(UTC)
        new_pc.frozen_by = locked_by
        new_pc.frozen_reason = reason
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("LOCK", locked_by, {"reason": reason})
        return new_pc

    def unlock(self, unlocked_by: str) -> Self:
        if self.status != PettyCashStatus.FROZEN:
            raise ValueError(f"Cannot unlock petty cash in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.ACTIVE
        new_pc.frozen_at = None
        new_pc.frozen_by = None
        new_pc.frozen_reason = None
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("UNLOCK", unlocked_by, {})
        return new_pc

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []

        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))

        if not self.verify_signature():
            errors.append("Signature verification failed")

        if self.status == PettyCashStatus.ACTIVE and self.needs_replenishment():
            warnings.append(
                f"Petty cash needs replenishment (balance: {self.current_balance}, threshold: {self.replenishment_threshold})"
            )

        if self.status == PettyCashStatus.DEPLETED and self.current_balance > 0:
            warnings.append("Petty cash is marked as DEPLETED but has positive balance")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "petty_cash_id": str(self.petty_cash_id),
            "petty_cash_code": self.petty_cash_code,
            "version": self.version,
        }

    def to_dict(self, include_transactions: bool = False) -> dict[str, Any]:
        result = {
            "petty_cash_id": str(self.petty_cash_id),
            "petty_cash_code": self.petty_cash_code,
            "petty_cash_name": self.petty_cash_name,
            "legal_entity_id": str(self.legal_entity_id),
            "currency": self.currency,
            "initial_fund": str(self.initial_fund),
            "current_balance": str(self.current_balance),
            "total_disbursements": str(self.total_disbursements),
            "replenishment_threshold": str(self.replenishment_threshold),
            "replenishment_amount": str(self.replenishment_amount),
            "status": self.status.value,
            "custodian_name": self.custodian_name,
            "custodian_employee_id": str(self.custodian_employee_id)
            if self.custodian_employee_id
            else None,
            "secondary_custodian_name": self.secondary_custodian_name,
            "secondary_custodian_employee_id": str(self.secondary_custodian_employee_id)
            if self.secondary_custodian_employee_id
            else None,
            "maximum_disbursement_per_transaction": str(self.maximum_disbursement_per_transaction),
            "daily_disbursement_limit": str(self.daily_disbursement_limit),
            "today_disbursements": str(self.today_disbursements),
            "monthly_disbursement_limit": str(self.monthly_disbursement_limit),
            "month_disbursements": str(self.month_disbursements),
            "last_replenishment_date": self.last_replenishment_date.isoformat()
            if self.last_replenishment_date
            else None,
            "last_audit_date": self.last_audit_date.isoformat() if self.last_audit_date else None,
            "last_audited_by": self.last_audited_by,
            "needs_replenishment": self.needs_replenishment(),
            "remaining_daily_limit": str(self.get_remaining_daily_limit()),
            "remaining_monthly_limit": str(self.get_remaining_monthly_limit()),
            "notes": self.notes,
            "suspended_at": self.suspended_at.isoformat() if self.suspended_at else None,
            "suspended_by": self.suspended_by,
            "suspended_reason": self.suspended_reason,
            "frozen_at": self.frozen_at.isoformat() if self.frozen_at else None,
            "frozen_by": self.frozen_by,
            "frozen_reason": self.frozen_reason,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": self.closed_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "signature": self.signature.to_dict() if self.signature else None,
        }
        if include_transactions:
            result["transactions"] = [t.to_dict() for t in self.transactions[-100:]]
            result["audit_logs"] = [a.to_dict() for a in self.audit_logs[-50:]]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            petty_cash_id=UUID(data["petty_cash_id"]),
            petty_cash_code=data["petty_cash_code"],
            petty_cash_name=data["petty_cash_name"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            currency=data["currency"],
            initial_fund=Decimal(data["initial_fund"]),
            current_balance=Decimal(data["current_balance"]),
            total_disbursements=Decimal(data["total_disbursements"]),
            replenishment_threshold=Decimal(data["replenishment_threshold"]),
            replenishment_amount=Decimal(data["replenishment_amount"]),
            status=PettyCashStatus(data["status"]),
            custodian_name=data["custodian_name"],
            custodian_employee_id=UUID(data["custodian_employee_id"])
            if data.get("custodian_employee_id")
            else None,
            secondary_custodian_name=data.get("secondary_custodian_name"),
            secondary_custodian_employee_id=UUID(data["secondary_custodian_employee_id"])
            if data.get("secondary_custodian_employee_id")
            else None,
            maximum_disbursement_per_transaction=Decimal(
                data.get("maximum_disbursement_per_transaction", "0")
            ),
            daily_disbursement_limit=Decimal(data.get("daily_disbursement_limit", "0")),
            today_disbursements=Decimal(data.get("today_disbursements", "0")),
            monthly_disbursement_limit=Decimal(data.get("monthly_disbursement_limit", "0")),
            month_disbursements=Decimal(data.get("month_disbursements", "0")),
            last_replenishment_date=datetime.fromisoformat(data["last_replenishment_date"])
            if data.get("last_replenishment_date")
            else None,
            last_audit_date=datetime.fromisoformat(data["last_audit_date"])
            if data.get("last_audit_date")
            else None,
            last_audited_by=data.get("last_audited_by"),
            notes=data.get("notes"),
            transactions=[],
            audit_logs=[],
            suspended_at=datetime.fromisoformat(data["suspended_at"])
            if data.get("suspended_at")
            else None,
            suspended_by=data.get("suspended_by"),
            suspended_reason=data.get("suspended_reason"),
            frozen_at=datetime.fromisoformat(data["frozen_at"]) if data.get("frozen_at") else None,
            frozen_by=data.get("frozen_by"),
            frozen_reason=data.get("frozen_reason"),
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None,
            closed_by=data.get("closed_by"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data["created_by"],
            version=data.get("version", 1),
        )

    def clone(self) -> Self:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "petty_cash_id", new_id)
        cloned.petty_cash_code = f"{self.petty_cash_code}_COPY"
        cloned.petty_cash_name = f"{self.petty_cash_name} (COPY)"
        cloned.initial_fund = Decimal(0)
        cloned.current_balance = Decimal(0)
        cloned.total_disbursements = Decimal(0)
        cloned.today_disbursements = Decimal(0)
        cloned.month_disbursements = Decimal(0)
        cloned.status = PettyCashStatus.PENDING_APPROVAL
        cloned.transactions = []
        cloned.audit_logs = []
        cloned.version = 1
        cloned.created_at = datetime.now(UTC)
        cloned.updated_at = datetime.now(UTC)
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.petty_cash_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "petty_cash_id": str(self.petty_cash_id),
            "current_balance": str(self.current_balance),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "signature": self.signature.to_dict() if self.signature else None,
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Self:
        new_pc = self._copy()
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("TOUCH", touched_by, {})
        return new_pc

    # ==================== STATUS CHECKERS ====================

    def is_active(self) -> bool:
        return self.status == PettyCashStatus.ACTIVE

    def is_depleted(self) -> bool:
        return self.status == PettyCashStatus.DEPLETED

    def is_suspended(self) -> bool:
        return self.status == PettyCashStatus.SUSPENDED

    def is_closed(self) -> bool:
        return self.status == PettyCashStatus.CLOSED

    def is_frozen(self) -> bool:
        return self.status == PettyCashStatus.FROZEN

    def is_under_audit(self) -> bool:
        return self.status == PettyCashStatus.UNDER_AUDIT

    def can_disburse(self) -> bool:
        return (
            self.status == PettyCashStatus.ACTIVE
            and self.current_balance > 0
            and not self.is_frozen()
        )

    def can_replenish(self) -> bool:
        return (
            self.status in (PettyCashStatus.ACTIVE, PettyCashStatus.DEPLETED)
            and not self.is_frozen()
        )

    def needs_replenishment(self) -> bool:
        return (
            self.current_balance <= self.replenishment_threshold
            and self.status == PettyCashStatus.ACTIVE
        )

    def get_remaining_daily_limit(self) -> Decimal:
        if self.daily_disbursement_limit <= 0:
            return Decimal("inf")
        remaining = self.daily_disbursement_limit - self.today_disbursements
        return remaining if remaining > 0 else Decimal(0)

    def get_remaining_monthly_limit(self) -> Decimal:
        if self.monthly_disbursement_limit <= 0:
            return Decimal("inf")
        remaining = self.monthly_disbursement_limit - self.month_disbursements
        return remaining if remaining > 0 else Decimal(0)

    def can_disburse_amount(self, amount: Decimal) -> tuple[bool, str | None]:
        """Check if disbursement amount is allowed."""
        if amount <= 0:
            return False, "Amount must be positive"

        if (
            self.maximum_disbursement_per_transaction > 0
            and amount > self.maximum_disbursement_per_transaction
        ):
            return (
                False,
                f"Amount {amount} exceeds maximum per transaction {self.maximum_disbursement_per_transaction}",
            )

        remaining_daily = self.get_remaining_daily_limit()
        if self.daily_disbursement_limit > 0 and amount > remaining_daily:
            return False, f"Amount {amount} exceeds remaining daily limit {remaining_daily}"

        remaining_monthly = self.get_remaining_monthly_limit()
        if self.monthly_disbursement_limit > 0 and amount > remaining_monthly:
            return False, f"Amount {amount} exceeds remaining monthly limit {remaining_monthly}"

        if amount > self.current_balance:
            return False, f"Insufficient balance: {self.current_balance} < {amount}"

        return True, None

    # ==================== RESET LIMITS ====================

    def reset_daily_limit(self, reset_by: str) -> Self:
        """Reset daily disbursement counter."""
        new_pc = self._copy()
        new_pc.today_disbursements = Decimal(0)
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("RESET_DAILY_LIMIT", reset_by, {})
        return new_pc

    def reset_monthly_limit(self, reset_by: str) -> Self:
        """Reset monthly disbursement counter."""
        new_pc = self._copy()
        new_pc.month_disbursements = Decimal(0)
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("RESET_MONTHLY_LIMIT", reset_by, {})
        return new_pc

    # ==================== TRANSACTION RECORDING ====================

    def _record_transaction(
        self,
        tx_type: PettyCashTransactionType,
        amount: Decimal,
        balance_before: Decimal,
        balance_after: Decimal,
        description: str,
        reference: str | None,
        created_by: str,
        requires_approval: bool = False,
    ) -> PettyCashTransaction:
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        return PettyCashTransaction(
            transaction_id=uuid4(),
            transaction_date=datetime.now(UTC),
            type=tx_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=description,
            reference=reference,
            created_by=created_by,
            created_at=datetime.now(UTC),
            approved_by=None if requires_approval else created_by,
            approved_at=None if requires_approval else datetime.now(UTC),
        )

    def init_fund(self, created_by: str, approved_by: str | None = None) -> Self:
        """Set initial fund (biasanya saat pembuatan)."""
        if self.transactions:
            raise ValueError("Petty cash already has transactions, cannot re-initialize")

        balance_before = Decimal(0)
        balance_after = self.initial_fund

        transaction = self._record_transaction(
            PettyCashTransactionType.INITIAL_FUND,
            self.initial_fund,
            balance_before,
            balance_after,
            f"Initial fund establishment: {self.petty_cash_name}",
            None,
            created_by,
        )

        new_pc = self._copy()
        new_pc.current_balance = balance_after
        new_pc.transactions = [transaction]
        new_pc.status = PettyCashStatus.ACTIVE if approved_by else PettyCashStatus.PENDING_APPROVAL
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("INIT_FUND", created_by, {"amount": str(self.initial_fund)})
        return new_pc

    def add_disbursement(
        self,
        amount: Decimal,
        description: str,
        created_by: str,
        reference: str | None = None,
        approved_by: str | None = None,
    ) -> Self:
        if not self.can_disburse():
            raise ValueError(f"Cannot disburse from petty cash in status {self.status.value}")

        can_disburse, error = self.can_disburse_amount(amount)
        if not can_disburse:
            raise ValueError(error)

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        balance_before = self.current_balance
        balance_after = balance_before - amount
        new_disbursements = self.total_disbursements + amount
        new_today = self.today_disbursements + amount
        new_month = self.month_disbursements + amount

        transaction = self._record_transaction(
            PettyCashTransactionType.DISBURSEMENT,
            amount,
            balance_before,
            balance_after,
            description,
            reference,
            created_by,
            requires_approval=approved_by is None,
        )

        if approved_by:
            object.__setattr__(transaction, "approved_by", approved_by)
            object.__setattr__(transaction, "approved_at", datetime.now(UTC))

        new_transactions = self.transactions + [transaction]
        new_status = self.status
        if balance_after <= self.replenishment_threshold:
            new_status = PettyCashStatus.DEPLETED

        new_pc = self._copy()
        new_pc.current_balance = balance_after
        new_pc.total_disbursements = new_disbursements
        new_pc.today_disbursements = new_today
        new_pc.month_disbursements = new_month
        new_pc.status = new_status
        new_pc.transactions = new_transactions
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit(
            "DISBURSEMENT", created_by, {"amount": str(amount), "description": description}
        )
        return new_pc

    def add_disbursement_batch(
        self,
        disbursements: list[tuple[Decimal, str, str | None]],
        created_by: str,
        approved_by: str | None = None,
    ) -> Self:
        total = Decimal(0)
        descriptions = []
        for amt, desc, ref in disbursements:
            if amt <= 0:
                raise ValueError(f"Disbursement amount must be positive: {amt}")
            total += amt
            descriptions.append(desc)

        return self.add_disbursement(total, "; ".join(descriptions), created_by, None, approved_by)

    def replenish(
        self,
        amount: Decimal,
        replenished_by: str,
        reference: str | None = None,
        approved_by: str | None = None,
    ) -> Self:
        if not self.can_replenish():
            raise ValueError(f"Cannot replenish petty cash in status {self.status.value}")
        if amount <= 0:
            raise ValueError(f"Replenishment amount must be positive: {amount}")

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        balance_before = self.current_balance
        balance_after = balance_before + amount

        transaction = self._record_transaction(
            PettyCashTransactionType.REPLENISHMENT,
            amount,
            balance_before,
            balance_after,
            f"Replenishment of {self.petty_cash_name}",
            reference,
            replenished_by,
            requires_approval=approved_by is None,
        )

        if approved_by:
            object.__setattr__(transaction, "approved_by", approved_by)
            object.__setattr__(transaction, "approved_at", datetime.now(UTC))

        new_transactions = self.transactions + [transaction]
        new_status = (
            PettyCashStatus.ACTIVE
            if balance_after > self.replenishment_threshold
            else PettyCashStatus.DEPLETED
        )

        new_pc = self._copy()
        new_pc.current_balance = balance_after
        new_pc.status = new_status
        new_pc.last_replenishment_date = datetime.now(UTC)
        new_pc.transactions = new_transactions
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("REPLENISH", replenished_by, {"amount": str(amount)})
        return new_pc

    def auto_replenish(
        self,
        replenished_by: str,
        reference: str | None = None,
        approved_by: str | None = None,
    ) -> Self | None:
        if self.needs_replenishment():
            return self.replenish(
                self.replenishment_amount,
                replenished_by,
                reference or "Auto-replenishment triggered",
                approved_by,
            )
        return None

    def adjust_balance(
        self,
        adjustment_amount: Decimal,
        reason: str,
        adjusted_by: str,
        approved_by: str | None = None,
        is_audit: bool = False,
    ) -> Self:
        if self.status == PettyCashStatus.CLOSED:
            raise ValueError("Cannot adjust closed petty cash")

        adjustment_amount = adjustment_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if adjustment_amount == 0:
            raise ValueError("Adjustment amount cannot be zero")

        balance_before = self.current_balance
        balance_after = balance_before + adjustment_amount
        if balance_after < 0:
            raise ValueError(f"Adjustment would make balance negative: {balance_after}")

        tx_type = (
            PettyCashTransactionType.AUDIT_ADJUSTMENT
            if is_audit
            else PettyCashTransactionType.ADJUSTMENT
        )

        transaction = self._record_transaction(
            tx_type,
            adjustment_amount,
            balance_before,
            balance_after,
            f"Adjustment: {reason}",
            None,
            adjusted_by,
            requires_approval=approved_by is None,
        )

        if approved_by:
            object.__setattr__(transaction, "approved_by", approved_by)
            object.__setattr__(transaction, "approved_at", datetime.now(UTC))

        new_transactions = self.transactions + [transaction]
        new_status = self.status

        if new_status == PettyCashStatus.ACTIVE and balance_after <= self.replenishment_threshold:
            new_status = PettyCashStatus.DEPLETED
        elif (
            new_status == PettyCashStatus.DEPLETED and balance_after > self.replenishment_threshold
        ):
            new_status = PettyCashStatus.ACTIVE

        # Update total disbursements if adjustment is negative (reducing balance)
        new_disbursements = self.total_disbursements
        if adjustment_amount < 0:
            new_disbursements += abs(adjustment_amount)

        new_pc = self._copy()
        new_pc.current_balance = balance_after
        new_pc.total_disbursements = new_disbursements
        new_pc.status = new_status
        new_pc.transactions = new_transactions
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit(
            "ADJUST",
            adjusted_by,
            {"amount": str(adjustment_amount), "reason": reason, "is_audit": is_audit},
        )
        return new_pc

    # ==================== TRANSFER METHODS ====================

    def transfer_in(
        self,
        amount: Decimal,
        from_source: str,
        description: str,
        created_by: str,
        approved_by: str | None = None,
    ) -> Self:
        return self.replenish(
            amount, created_by, f"{description} (from {from_source})", approved_by
        )

    def transfer_out(
        self,
        amount: Decimal,
        to_destination: str,
        description: str,
        created_by: str,
        approved_by: str | None = None,
    ) -> Self:
        return self.add_disbursement(
            amount, f"{description} (to {to_destination})", created_by, None, approved_by
        )

    # ==================== SUSPEND & ACTIVATE ====================

    def suspend(self, suspended_by: str, reason: str) -> Self:
        if self.status == PettyCashStatus.CLOSED:
            raise ValueError("Cannot suspend closed petty cash")
        if self.status == PettyCashStatus.SUSPENDED:
            raise ValueError("Petty cash already suspended")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.SUSPENDED
        new_pc.suspended_at = datetime.now(UTC)
        new_pc.suspended_by = suspended_by
        new_pc.suspended_reason = reason
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("SUSPEND", suspended_by, {"reason": reason})
        return new_pc

    def activate_suspended(self, activated_by: str) -> Self:
        if self.status != PettyCashStatus.SUSPENDED:
            raise ValueError(f"Cannot activate petty cash in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = (
            PettyCashStatus.ACTIVE
            if self.current_balance > self.replenishment_threshold
            else PettyCashStatus.DEPLETED
        )
        new_pc.suspended_at = None
        new_pc.suspended_by = None
        new_pc.suspended_reason = None
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("ACTIVATE", activated_by, {})
        return new_pc

    def mark_under_audit(self, audited_by: str, reason: str) -> Self:
        if self.status != PettyCashStatus.ACTIVE:
            raise ValueError(f"Cannot mark under audit in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = PettyCashStatus.UNDER_AUDIT
        new_pc.last_audit_date = datetime.now(UTC)
        new_pc.last_audited_by = audited_by
        new_pc.notes = f"{self.notes}\n[AUDIT] {reason}" if self.notes else f"[AUDIT] {reason}"
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("UNDER_AUDIT", audited_by, {"reason": reason})
        return new_pc

    def complete_audit(self, completed_by: str, findings: str | None = None) -> Self:
        if self.status != PettyCashStatus.UNDER_AUDIT:
            raise ValueError(f"Cannot complete audit in status {self.status.value}")

        new_pc = self._copy()
        new_pc.status = (
            PettyCashStatus.ACTIVE
            if self.current_balance > self.replenishment_threshold
            else PettyCashStatus.DEPLETED
        )
        if findings:
            new_pc.notes = (
                f"{self.notes}\n[AUDIT COMPLETED] {findings}"
                if self.notes
                else f"[AUDIT COMPLETED] {findings}"
            )
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("AUDIT_COMPLETED", completed_by, {"findings": findings})
        return new_pc

    # ==================== CLOSE ====================

    def close(self, closed_by: str, final_balance: Decimal | None = None) -> Self:
        if self.status == PettyCashStatus.CLOSED:
            raise ValueError("Petty cash already closed")

        close_balance = final_balance if final_balance is not None else self.current_balance
        close_balance = close_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        if close_balance != self.current_balance:
            raise ValueError(
                f"Final balance {close_balance} does not match current balance {self.current_balance}"
            )

        if close_balance != 0:
            # Create a closing adjustment to zero out the balance
            if close_balance > 0:
                # Positive balance - need to disburse the remaining
                new_pc = self.add_disbursement(
                    close_balance, "Closing: remaining balance disbursed", closed_by
                )
                new_pc = new_pc._copy()
            else:
                # Negative balance - need to replenish
                new_pc = self.replenish(
                    abs(close_balance), closed_by, "Closing: negative balance adjustment"
                )
                new_pc = new_pc._copy()
        else:
            new_pc = self._copy()

        transaction = self._record_transaction(
            PettyCashTransactionType.CLOSING,
            Decimal(0),
            new_pc.current_balance,
            new_pc.current_balance,
            f"Closed by {closed_by}",
            None,
            closed_by,
        )

        new_pc.transactions = new_pc.transactions + [transaction]
        new_pc.status = PettyCashStatus.CLOSED
        new_pc.closed_at = datetime.now(UTC)
        new_pc.closed_by = closed_by
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("CLOSE", closed_by, {"final_balance": str(close_balance)})
        return new_pc

    # ==================== CUSTODIAN MANAGEMENT ====================

    def can_change_custodian(self) -> bool:
        return self.status in (PettyCashStatus.ACTIVE, PettyCashStatus.DEPLETED)

    def change_custodian(
        self,
        new_custodian_name: str,
        new_custodian_employee_id: UUID | None,
        changed_by: str,
        effective_date: datetime | None = None,
    ) -> Self:
        if not self.can_change_custodian():
            raise ValueError(f"Cannot change custodian in status {self.status.value}")

        old_custodian = self.custodian_name

        new_pc = self._copy()
        new_pc.custodian_name = new_custodian_name
        new_pc.custodian_employee_id = new_custodian_employee_id
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit(
            "CHANGE_CUSTODIAN",
            changed_by,
            {
                "old_custodian": old_custodian,
                "new_custodian": new_custodian_name,
                "effective_date": effective_date.isoformat() if effective_date else None,
            },
        )
        return new_pc

    def change_secondary_custodian(
        self,
        new_secondary_name: str | None,
        new_secondary_employee_id: UUID | None,
        changed_by: str,
    ) -> Self:
        new_pc = self._copy()
        new_pc.secondary_custodian_name = new_secondary_name
        new_pc.secondary_custodian_employee_id = new_secondary_employee_id
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit(
            "CHANGE_SECONDARY_CUSTODIAN",
            changed_by,
            {
                "new_secondary": new_secondary_name,
            },
        )
        return new_pc

    # ==================== SIGNATURE METHODS ====================

    def sign(self, signed_by: str) -> Self:
        new_pc = self._copy()
        new_pc.signature = PettyCashFundSignature.create(self, signed_by)
        new_pc.updated_at = datetime.now(UTC)
        new_pc.version = self.version + 1
        new_pc._record_audit("SIGN", signed_by, {})
        return new_pc

    def verify_signature(self) -> bool:
        if not self.signature:
            return False
        return self.signature.verify(self)

    # ==================== QUERY METHODS ====================

    def get_transactions(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if limit <= 0 or offset < 0:
            return []
        reversed_txs = self.transactions[::-1]
        return [t.to_dict() for t in reversed_txs[offset : offset + limit]]

    def get_disbursements(self) -> list[PettyCashTransaction]:
        return [t for t in self.transactions if t.type == PettyCashTransactionType.DISBURSEMENT]

    def get_replenishments(self) -> list[PettyCashTransaction]:
        return [t for t in self.transactions if t.type == PettyCashTransactionType.REPLENISHMENT]

    def get_adjustments(self) -> list[PettyCashTransaction]:
        return [
            t
            for t in self.transactions
            if t.type
            in (PettyCashTransactionType.ADJUSTMENT, PettyCashTransactionType.AUDIT_ADJUSTMENT)
        ]

    def get_transactions_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[PettyCashTransaction]:
        return [t for t in self.transactions if start_date <= t.transaction_date <= end_date]

    def get_transactions_by_type(
        self, tx_type: PettyCashTransactionType
    ) -> list[PettyCashTransaction]:
        return [t for t in self.transactions if t.type == tx_type]

    def get_total_disbursement_since(self, since_date: datetime) -> Decimal:
        total = Decimal(0)
        for t in self.transactions:
            if t.type == PettyCashTransactionType.DISBURSEMENT and t.transaction_date >= since_date:
                total += t.amount
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_daily_summary(self, target_date: date | None = None) -> dict[str, Any]:
        if target_date is None:
            target_date = datetime.now(UTC).date()
        start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC)
        end = start + timedelta(days=1)

        daily_disbursements = sum(
            t.amount
            for t in self.transactions
            if t.type == PettyCashTransactionType.DISBURSEMENT
            and start <= t.transaction_date <= end
        )
        daily_replenishments = sum(
            t.amount
            for t in self.transactions
            if t.type == PettyCashTransactionType.REPLENISHMENT
            and start <= t.transaction_date <= end
        )
        daily_adjustments = sum(
            t.amount
            for t in self.transactions
            if t.type
            in (PettyCashTransactionType.ADJUSTMENT, PettyCashTransactionType.AUDIT_ADJUSTMENT)
            and start <= t.transaction_date <= end
        )

        return {
            "date": target_date.isoformat(),
            "opening_balance": str(self.get_balance_at_date(start - timedelta(microseconds=1))),
            "disbursements": str(daily_disbursements),
            "replenishments": str(daily_replenishments),
            "adjustments": str(daily_adjustments),
            "closing_balance": str(self.current_balance),
        }

    def get_balance_at_date(self, target_date: datetime) -> Decimal:
        balance = self.initial_fund
        for tx in self.transactions:
            if tx.transaction_date <= target_date:
                balance += tx.amount
        return balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_monthly_summary(self, year: int, month: int) -> dict[str, Any]:
        start = datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=UTC)
        else:
            end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=UTC)

        monthly_disbursements = sum(
            t.amount
            for t in self.transactions
            if t.type == PettyCashTransactionType.DISBURSEMENT and start <= t.transaction_date < end
        )
        monthly_replenishments = sum(
            t.amount
            for t in self.transactions
            if t.type == PettyCashTransactionType.REPLENISHMENT
            and start <= t.transaction_date < end
        )

        return {
            "year": year,
            "month": month,
            "disbursements": str(monthly_disbursements),
            "replenishments": str(monthly_replenishments),
            "net_flow": str(monthly_replenishments - monthly_disbursements),
        }

    def get_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.audit_logs[-limit:]]

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> Self:
        return PettyCashFundEntity(
            petty_cash_id=self.petty_cash_id,
            petty_cash_code=self.petty_cash_code,
            petty_cash_name=self.petty_cash_name,
            legal_entity_id=self.legal_entity_id,
            currency=self.currency,
            initial_fund=self.initial_fund,
            current_balance=self.current_balance,
            total_disbursements=self.total_disbursements,
            replenishment_threshold=self.replenishment_threshold,
            replenishment_amount=self.replenishment_amount,
            status=self.status,
            custodian_name=self.custodian_name,
            custodian_employee_id=self.custodian_employee_id,
            secondary_custodian_name=self.secondary_custodian_name,
            secondary_custodian_employee_id=self.secondary_custodian_employee_id,
            maximum_disbursement_per_transaction=self.maximum_disbursement_per_transaction,
            daily_disbursement_limit=self.daily_disbursement_limit,
            today_disbursements=self.today_disbursements,
            monthly_disbursement_limit=self.monthly_disbursement_limit,
            month_disbursements=self.month_disbursements,
            last_replenishment_date=self.last_replenishment_date,
            last_audit_date=self.last_audit_date,
            last_audited_by=self.last_audited_by,
            notes=self.notes,
            transactions=self.transactions.copy(),
            audit_logs=self.audit_logs.copy(),
            suspended_at=self.suspended_at,
            suspended_by=self.suspended_by,
            suspended_reason=self.suspended_reason,
            frozen_at=self.frozen_at,
            frozen_by=self.frozen_by,
            frozen_reason=self.frozen_reason,
            closed_at=self.closed_at,
            closed_by=self.closed_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            signature=self.signature,
        )


# ============================================================================
# Alias for Service Layer
# ============================================================================

PettyCashFund = PettyCashFundEntity


# ============================================================================
# Repository Interface (Real Implementation)
# ============================================================================


class PettyCashRepository:
    """Repository for PettyCashFund with in-memory storage."""

    _storage: ClassVar[dict[UUID, dict[UUID, PettyCashFundEntity]]] = {}
    _storage_by_code: ClassVar[dict[UUID, dict[str, PettyCashFundEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, PettyCashFundEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    def _get_code_storage(cls, legal_entity_id: UUID) -> dict[str, PettyCashFundEntity]:
        if legal_entity_id not in cls._storage_by_code:
            cls._storage_by_code[legal_entity_id] = {}
        return cls._storage_by_code[legal_entity_id]

    async def get_by_id(
        self, petty_cash_id: UUID, legal_entity_id: UUID
    ) -> PettyCashFundEntity | None:
        storage = self._get_storage(legal_entity_id)
        return storage.get(petty_cash_id)

    async def get_by_code(
        self, petty_cash_code: str, legal_entity_id: UUID
    ) -> PettyCashFundEntity | None:
        code_storage = self._get_code_storage(legal_entity_id)
        return code_storage.get(petty_cash_code)

    async def get_by_custodian(
        self, custodian_employee_id: UUID, legal_entity_id: UUID
    ) -> list[PettyCashFundEntity]:
        storage = self._get_storage(legal_entity_id)
        return [pc for pc in storage.values() if pc.custodian_employee_id == custodian_employee_id]

    async def get_by_status(
        self, status: PettyCashStatus, legal_entity_id: UUID
    ) -> list[PettyCashFundEntity]:
        storage = self._get_storage(legal_entity_id)
        return [pc for pc in storage.values() if pc.status == status]

    async def get_active(self, legal_entity_id: UUID) -> list[PettyCashFundEntity]:
        storage = self._get_storage(legal_entity_id)
        return [pc for pc in storage.values() if pc.is_active()]

    async def get_need_replenishment(self, legal_entity_id: UUID) -> list[PettyCashFundEntity]:
        storage = self._get_storage(legal_entity_id)
        return [pc for pc in storage.values() if pc.needs_replenishment()]

    async def get_all(self, legal_entity_id: UUID) -> list[PettyCashFundEntity]:
        storage = self._get_storage(legal_entity_id)
        return list(storage.values())

    async def count(self, legal_entity_id: UUID) -> int:
        storage = self._get_storage(legal_entity_id)
        return len(storage)

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[PettyCashFundEntity]:
        funds = await self.get_all(legal_entity_id)
        funds.sort(key=lambda x: x.created_at, reverse=True)
        return funds[offset : offset + limit]

    async def save(self, petty_cash: PettyCashFundEntity, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        code_storage = self._get_code_storage(legal_entity_id)
        storage[petty_cash.petty_cash_id] = petty_cash
        code_storage[petty_cash.petty_cash_code] = petty_cash

    async def update(self, petty_cash: PettyCashFundEntity, legal_entity_id: UUID) -> None:
        await self.save(petty_cash, legal_entity_id)

    async def delete(self, petty_cash_id: UUID, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        code_storage = self._get_code_storage(legal_entity_id)
        if petty_cash_id in storage:
            pc = storage[petty_cash_id]
            if pc.petty_cash_code in code_storage:
                del code_storage[pc.petty_cash_code]
            del storage[petty_cash_id]

    async def clear(self, legal_entity_id: UUID) -> None:
        if legal_entity_id in self._storage:
            self._storage[legal_entity_id] = {}
        if legal_entity_id in self._storage_by_code:
            self._storage_by_code[legal_entity_id] = {}


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "PettyCashAuditLog",
    "PettyCashFund",
    "PettyCashFundEntity",
    "PettyCashFundSignature",
    "PettyCashRepository",
    "PettyCashStatus",
    "PettyCashTransaction",
    "PettyCashTransactionType",
]
