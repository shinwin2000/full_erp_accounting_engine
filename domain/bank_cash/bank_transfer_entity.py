#!/usr/bin/env python3
"""
Module: bank_transfer_entity.py
Layer: Domain / Bank & Cash
Responsibility: Transfer antar rekening.
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
# Enums
# ============================================================================


class TransferStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    REVERSED = "reversed"

    @classmethod
    def can_transition(cls, from_status: TransferStatus, to_status: TransferStatus) -> bool:
        allowed = {
            cls.DRAFT: {cls.SUBMITTED, cls.CANCELLED},
            cls.SUBMITTED: {cls.PENDING, cls.REJECTED, cls.CANCELLED},
            cls.PENDING: {cls.PROCESSING, cls.FAILED, cls.CANCELLED},
            cls.PROCESSING: {cls.COMPLETED, cls.FAILED},
            cls.COMPLETED: {cls.REVERSED},
            cls.FAILED: {cls.DRAFT},
            cls.CANCELLED: set(),
            cls.REJECTED: {cls.DRAFT},
            cls.REVERSED: set(),
        }
        return to_status in allowed.get(from_status, set())


class TransferType(Enum):
    INTERNAL = "internal"  # Same bank, same legal entity
    EXTERNAL = "external"  # Different bank
    INTERCOMPANY = "intercompany"  # Different legal entity
    INTERNATIONAL = "international"  # Cross-border
    BATCH = "batch"  # Part of batch transfer


class TransferPriority(Enum):
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    SCHEDULED = "scheduled"


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class TransferFee:
    """
    Transfer fee configuration (value object, NOT a monetary amount).

    This is a configuration object that defines how fees are calculated.
    The actual monetary fee amount is stored in `fee_amount` field.

    Attributes:
        flat_fee: Biaya flat (fixed amount) as Decimal.
        percentage_fee: Biaya persentase dari jumlah transfer (as Decimal).
        vat_percentage: Persentase PPN atas biaya (as Decimal).
        additional_fees: Biaya tambahan lainnya (dict of Decimal).
    """

    flat_fee: Decimal = Decimal(0)
    percentage_fee: Decimal = Decimal(0)
    vat_percentage: Decimal = Decimal(11)
    additional_fees: dict[str, Decimal] = field(default_factory=dict)

    def calculate(self, amount: Decimal) -> Decimal:
        """Calculate total fee as Decimal (monetary amount)."""
        total = self.flat_fee
        total += amount * self.percentage_fee / Decimal(100)
        total += sum(self.additional_fees.values())

        # Add VAT
        vat = total * self.vat_percentage / Decimal(100)
        total += vat

        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def breakdown(self, amount: Decimal) -> dict[str, str]:
        """Get fee breakdown as strings for serialization."""
        flat = self.flat_fee
        percentage = amount * self.percentage_fee / Decimal(100)
        subtotal = flat + percentage + sum(self.additional_fees.values())
        vat = subtotal * self.vat_percentage / Decimal(100)

        return {
            "flat_fee": str(flat),
            "percentage_fee": str(percentage),
            "subtotal": str(subtotal),
            "vat": str(vat),
            "total": str(subtotal + vat),
            **{k: str(v) for k, v in self.additional_fees.items()},
        }


@dataclass(frozen=True)
class TransferSignature:
    """Digital signature for transfer."""

    transfer_id: UUID
    version: int
    hash_value: str
    signed_at: datetime
    signed_by: str

    @classmethod
    def create(cls, transfer: BankTransferEntity, signed_by: str) -> Self:
        data = f"{transfer.transfer_id}{transfer.version}{transfer.amount}{transfer.transfer_date}"
        hash_value = hashlib.sha3_256(data.encode()).hexdigest()
        return cls(
            transfer_id=transfer.transfer_id,
            version=transfer.version,
            hash_value=hash_value,
            signed_at=datetime.now(UTC),
            signed_by=signed_by,
        )

    def verify(self, transfer: BankTransferEntity) -> bool:
        data = f"{transfer.transfer_id}{transfer.version}{transfer.amount}{transfer.transfer_date}"
        expected = hashlib.sha3_256(data.encode()).hexdigest()
        return self.hash_value == expected


# ============================================================================
# Bank Transfer Entity
# ============================================================================


@dataclass
class BankTransferEntity:
    """
    Bank transfer entity with full lifecycle.

    All monetary fields use Decimal for precision.
    The `fee_config` field is a TransferFee value object (configuration), NOT a monetary amount.
    The actual monetary fee amount is in `fee_amount` (Decimal).

    Attributes:
        fee_config: Transfer fee configuration (value object, not monetary).
        fee_amount: Actual fee amount in Decimal (monetary).
        fee_currency: Currency of the fee.
    """

    transfer_id: UUID
    transfer_number: str
    transfer_type: TransferType
    from_account_id: UUID
    from_account_number: str
    to_account_id: UUID | None  # Can be None for external transfers
    to_account_number: str
    to_bank_code: str | None
    to_bank_name: str | None
    to_account_name: str
    amount: Decimal
    currency: str
    transfer_date: date
    value_date: date | None
    status: TransferStatus
    priority: TransferPriority = TransferPriority.NORMAL
    reference: str | None = None
    description: str = ""

    # --- Fee fields: fee_config is value object, fee_amount is monetary ---
    fee_config: TransferFee = field(default_factory=TransferFee)  # value object, not monetary
    fee_amount: Decimal = Decimal(0)  # actual monetary fee amount
    fee_currency: str = "IDR"

    # Approval
    approval_level_required: int = 1
    current_approval_level: int = 0
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejected_by: UUID | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    # Processing
    processed_by: UUID | None = None
    processed_at: datetime | None = None
    failure_reason: str | None = None
    failure_code: str | None = None

    # Reversal
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None
    reversal_reason: str | None = None
    reversal_transfer_id: UUID | None = None

    # Scheduling
    scheduled_date: date | None = None
    scheduled_by: UUID | None = None

    # Metadata
    legal_entity_id: UUID | None = None
    created_by: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    version: int = 1

    # Security
    signature: TransferSignature | None = None
    requires_two_factor: bool = False
    two_factor_verified_at: datetime | None = None
    two_factor_verified_by: UUID | None = None

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    # --------------------------------------------------------------------------
    # Property to maintain backward compatibility (access via .fee)
    # --------------------------------------------------------------------------
    @property
    def fee(self) -> TransferFee:
        """Backward-compatible accessor for fee_config."""
        return self.fee_config

    def __post_init__(self) -> None:
        self._validate()
        self._record_audit("CREATE", str(self.created_by), {})

    def _validate(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Transfer amount must be positive: {self.amount}")
        self.amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        if self.transfer_type == TransferType.INTERNAL and self.to_account_id is None:
            raise ValueError("Internal transfer requires to_account_id")

        if self.transfer_date > date.today():
            raise ValueError("Transfer date cannot be in the future")

        if self.scheduled_date and self.scheduled_date < date.today():
            raise ValueError("Scheduled date cannot be in the past")

        if self.updated_at is None:
            object.__setattr__(self, "updated_at", self.created_at)

        if not TransferStatus.can_transition(self.status, self.status):
            if self.status not in TransferStatus:
                raise ValueError(f"Invalid status: {self.status}")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "transfer_id": str(self.transfer_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: UUID) -> Self:
        self._record_audit("CREATE", str(created_by), {"amount": str(self.amount)})
        return self

    def update(self, updated_by: UUID, **kwargs) -> Self:
        if self.status not in (
            TransferStatus.DRAFT,
            TransferStatus.FAILED,
            TransferStatus.REJECTED,
        ):
            raise ValueError(f"Cannot update transfer in status {self.status.value}")

        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "transfer_id",
                "created_at",
                "created_by",
                "version",
            ):
                data[key] = value

        new_transfer = self.from_dict(data)
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("UPDATE", str(updated_by), {"changes": kwargs})
        return new_transfer

    def delete(self, deleted_by: UUID, reason: str | None = None) -> Self:
        if self.status in (TransferStatus.COMPLETED, TransferStatus.PROCESSING):
            raise ValueError(f"Cannot delete transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.CANCELLED
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("DELETE", str(deleted_by), {"reason": reason})
        return new_transfer

    def restore(self, restored_by: UUID) -> Self:
        if self.status != TransferStatus.CANCELLED:
            raise ValueError(f"Cannot restore transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.DRAFT
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("RESTORE", str(restored_by), {})
        return new_transfer

    def activate(self, activated_by: UUID) -> Self:
        if self.status != TransferStatus.DRAFT:
            raise ValueError(f"Cannot activate transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.SUBMITTED
        new_transfer.submitted_by = activated_by
        new_transfer.submitted_at = datetime.now(UTC)
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("ACTIVATE", str(activated_by), {})
        return new_transfer

    def deactivate(self, deactivated_by: UUID, reason: str | None = None) -> Self:
        if self.status != TransferStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.DRAFT
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("DEACTIVATE", str(deactivated_by), {"reason": reason})
        return new_transfer

    def lock(self, locked_by: UUID, reason: str) -> Self:
        new_transfer = self._copy()
        new_transfer.approval_history.append(
            {
                "action": "LOCK",
                "by": str(locked_by),
                "reason": reason,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("LOCK", str(locked_by), {"reason": reason})
        return new_transfer

    def unlock(self, unlocked_by: UUID) -> Self:
        new_transfer = self._copy()
        new_transfer.approval_history.append(
            {
                "action": "UNLOCK",
                "by": str(unlocked_by),
                "at": datetime.now(UTC).isoformat(),
            }
        )
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("UNLOCK", str(unlocked_by), {})
        return new_transfer

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []

        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))

        if self.amount > Decimal("1000000000"):
            warnings.append("Transfer amount exceeds 1 billion")

        if self.status == TransferStatus.PENDING and (datetime.now(UTC) - self.created_at).days > 7:
            warnings.append("Transfer has been pending for over 7 days")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "transfer_id": str(self.transfer_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        # For backward compatibility, we still export as "fee"
        return {
            "transfer_id": str(self.transfer_id),
            "transfer_number": self.transfer_number,
            "transfer_type": self.transfer_type.value,
            "from_account_id": str(self.from_account_id),
            "from_account_number": self.from_account_number,
            "to_account_id": str(self.to_account_id) if self.to_account_id else None,
            "to_account_number": self.to_account_number,
            "to_bank_code": self.to_bank_code,
            "to_bank_name": self.to_bank_name,
            "to_account_name": self.to_account_name,
            "amount": str(self.amount),
            "currency": self.currency,
            "transfer_date": self.transfer_date.isoformat(),
            "value_date": self.value_date.isoformat() if self.value_date else None,
            "status": self.status.value,
            "priority": self.priority.value,
            "reference": self.reference,
            "description": self.description,
            "fee": self.fee_config.to_dict() if hasattr(self.fee_config, "to_dict") else self.fee_config.breakdown(self.amount),
            "fee_amount": str(self.fee_amount),
            "fee_currency": self.fee_currency,
            "fee_breakdown": self.fee_config.breakdown(self.amount) if self.fee_config else {},
            "approval_level_required": self.approval_level_required,
            "current_approval_level": self.current_approval_level,
            "approval_history": self.approval_history,
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejection_reason": self.rejection_reason,
            "processed_by": str(self.processed_by) if self.processed_by else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "failure_reason": self.failure_reason,
            "failure_code": self.failure_code,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "reversed_by": str(self.reversed_by) if self.reversed_by else None,
            "reversal_reason": self.reversal_reason,
            "reversal_transfer_id": str(self.reversal_transfer_id)
            if self.reversal_transfer_id
            else None,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "scheduled_by": str(self.scheduled_by) if self.scheduled_by else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_by": str(self.created_by),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "version": self.version,
            "requires_two_factor": self.requires_two_factor,
            "two_factor_verified_at": self.two_factor_verified_at.isoformat()
            if self.two_factor_verified_at
            else None,
            "two_factor_verified_by": str(self.two_factor_verified_by)
            if self.two_factor_verified_by
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        # Handle both old "fee" and new "fee_config"
        fee_data = data.get("fee", {})
        if isinstance(fee_data, dict):
            fee_config = TransferFee(**fee_data)
        else:
            fee_config = TransferFee()

        return cls(
            transfer_id=UUID(data["transfer_id"]),
            transfer_number=data["transfer_number"],
            transfer_type=TransferType(data["transfer_type"]),
            from_account_id=UUID(data["from_account_id"]),
            from_account_number=data["from_account_number"],
            to_account_id=UUID(data["to_account_id"]) if data.get("to_account_id") else None,
            to_account_number=data["to_account_number"],
            to_bank_code=data.get("to_bank_code"),
            to_bank_name=data.get("to_bank_name"),
            to_account_name=data["to_account_name"],
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            transfer_date=date.fromisoformat(data["transfer_date"]),
            value_date=date.fromisoformat(data["value_date"]) if data.get("value_date") else None,
            status=TransferStatus(data["status"]),
            priority=TransferPriority(data.get("priority", "normal")),
            reference=data.get("reference"),
            description=data.get("description", ""),
            fee_config=fee_config,
            fee_amount=Decimal(data.get("fee_amount", "0")),
            fee_currency=data.get("fee_currency", "IDR"),
            approval_level_required=data.get("approval_level_required", 1),
            current_approval_level=data.get("current_approval_level", 0),
            approval_history=data.get("approval_history", []),
            submitted_by=UUID(data["submitted_by"]) if data.get("submitted_by") else None,
            submitted_at=datetime.fromisoformat(data["submitted_at"])
            if data.get("submitted_at")
            else None,
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            rejected_by=UUID(data["rejected_by"]) if data.get("rejected_by") else None,
            rejected_at=datetime.fromisoformat(data["rejected_at"])
            if data.get("rejected_at")
            else None,
            rejection_reason=data.get("rejection_reason"),
            processed_by=UUID(data["processed_by"]) if data.get("processed_by") else None,
            processed_at=datetime.fromisoformat(data["processed_at"])
            if data.get("processed_at")
            else None,
            failure_reason=data.get("failure_reason"),
            failure_code=data.get("failure_code"),
            reversed_at=datetime.fromisoformat(data["reversed_at"])
            if data.get("reversed_at")
            else None,
            reversed_by=UUID(data["reversed_by"]) if data.get("reversed_by") else None,
            reversal_reason=data.get("reversal_reason"),
            reversal_transfer_id=UUID(data["reversal_transfer_id"])
            if data.get("reversal_transfer_id")
            else None,
            scheduled_date=date.fromisoformat(data["scheduled_date"])
            if data.get("scheduled_date")
            else None,
            scheduled_by=UUID(data["scheduled_by"]) if data.get("scheduled_by") else None,
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            created_by=UUID(data.get("created_by", str(uuid4()))),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            version=data.get("version", 1),
            requires_two_factor=data.get("requires_two_factor", False),
            two_factor_verified_at=datetime.fromisoformat(data["two_factor_verified_at"])
            if data.get("two_factor_verified_at")
            else None,
            two_factor_verified_by=UUID(data["two_factor_verified_by"])
            if data.get("two_factor_verified_by")
            else None,
        )

    def clone(self) -> Self:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "transfer_id", new_id)
        cloned.transfer_number = f"{self.transfer_number}_COPY_{uuid4().hex[:4]}"
        cloned.version = 1
        cloned.created_at = datetime.now(UTC)
        cloned.updated_at = None
        cloned.status = TransferStatus.DRAFT
        cloned._record_audit("CLONE", str(self.created_by), {"source": str(self.transfer_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "transfer_id": str(self.transfer_id),
            "amount": str(self.amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: UUID) -> Self:
        new_transfer = self._copy()
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("TOUCH", str(touched_by), {})
        return new_transfer

    # ==================== Status Checkers ====================

    def is_draft(self) -> bool:
        return self.status == TransferStatus.DRAFT

    def is_submitted(self) -> bool:
        return self.status == TransferStatus.SUBMITTED

    def is_pending(self) -> bool:
        return self.status == TransferStatus.PENDING

    def is_processing(self) -> bool:
        return self.status == TransferStatus.PROCESSING

    def is_completed(self) -> bool:
        return self.status == TransferStatus.COMPLETED

    def is_failed(self) -> bool:
        return self.status == TransferStatus.FAILED

    def is_cancelled(self) -> bool:
        return self.status == TransferStatus.CANCELLED

    def is_rejected(self) -> bool:
        return self.status == TransferStatus.REJECTED

    def is_reversed(self) -> bool:
        return self.status == TransferStatus.REVERSED

    def can_edit(self) -> bool:
        return self.status in (TransferStatus.DRAFT, TransferStatus.FAILED, TransferStatus.REJECTED)

    def can_submit(self) -> bool:
        return self.status == TransferStatus.DRAFT

    def can_approve(self, level: int) -> bool:
        return (
            self.status == TransferStatus.SUBMITTED
            and self.current_approval_level == level - 1
            and level <= self.approval_level_required
        )

    def can_reject(self) -> bool:
        return self.status == TransferStatus.SUBMITTED

    def can_process(self) -> bool:
        return self.status == TransferStatus.PENDING

    def can_cancel(self) -> bool:
        return self.status not in (
            TransferStatus.COMPLETED,
            TransferStatus.CANCELLED,
            TransferStatus.REVERSED,
        )

    def can_reverse(self) -> bool:
        return self.status == TransferStatus.COMPLETED and self.reversal_transfer_id is None

    # ==================== Workflow Actions ====================

    def submit(self, submitted_by: UUID) -> Self:
        if not self.can_submit():
            raise ValueError(f"Cannot submit transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.SUBMITTED
        new_transfer.submitted_by = submitted_by
        new_transfer.submitted_at = datetime.now(UTC)
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("SUBMIT", str(submitted_by), {})
        return new_transfer

    def approve(self, level: int, approved_by: UUID, comment: str | None = None) -> Self:
        if not self.can_approve(level):
            raise ValueError(f"Cannot approve at level {level} in status {self.status.value}")

        new_history = self.approval_history + [
            {
                "level": level,
                "approver": str(approved_by),
                "action": "APPROVED",
                "comment": comment,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ]

        new_current_level = level
        new_status = self.status
        new_approved_by = self.approved_by
        new_approved_at = self.approved_at

        if level == self.approval_level_required:
            new_status = TransferStatus.PENDING
            new_approved_by = approved_by
            new_approved_at = datetime.now(UTC)

        new_transfer = self._copy()
        new_transfer.approval_history = new_history
        new_transfer.current_approval_level = new_current_level
        new_transfer.status = new_status
        new_transfer.approved_by = new_approved_by
        new_transfer.approved_at = new_approved_at
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit(
            "APPROVE", str(approved_by), {"level": level, "comment": comment}
        )
        return new_transfer

    def reject(self, rejected_by: UUID, reason: str) -> Self:
        if not self.can_reject():
            raise ValueError(f"Cannot reject transfer in status {self.status.value}")

        new_history = self.approval_history + [
            {
                "level": self.current_approval_level + 1,
                "approver": str(rejected_by),
                "action": "REJECTED",
                "comment": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ]

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.REJECTED
        new_transfer.approval_history = new_history
        new_transfer.rejected_by = rejected_by
        new_transfer.rejected_at = datetime.now(UTC)
        new_transfer.rejection_reason = reason
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("REJECT", str(rejected_by), {"reason": reason})
        return new_transfer

    def process(self, processed_by: UUID) -> Self:
        if not self.can_process():
            raise ValueError(f"Cannot process transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.PROCESSING
        new_transfer.processed_by = processed_by
        new_transfer.processed_at = datetime.now(UTC)
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("PROCESS", str(processed_by), {})
        return new_transfer

    def complete(self, completed_by: UUID, reference: str | None = None) -> Self:
        if self.status != TransferStatus.PROCESSING:
            raise ValueError(f"Cannot complete transfer in status {self.status.value}")

        # Calculate fee if not already calculated
        fee_amount = self.fee_config.calculate(self.amount) if self.fee_config else Decimal(0)

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.COMPLETED
        new_transfer.fee_amount = fee_amount
        if reference:
            new_transfer.reference = reference
        new_transfer.completed_at = datetime.now(UTC)
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("COMPLETE", str(completed_by), {"reference": reference})
        return new_transfer

    def fail(self, failed_by: UUID, reason: str, failure_code: str | None = None) -> Self:
        if self.status not in (
            TransferStatus.SUBMITTED,
            TransferStatus.PENDING,
            TransferStatus.PROCESSING,
        ):
            raise ValueError(f"Cannot fail transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.FAILED
        new_transfer.failure_reason = reason
        new_transfer.failure_code = failure_code
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("FAIL", str(failed_by), {"reason": reason, "code": failure_code})
        return new_transfer

    def cancel(self, cancelled_by: UUID, reason: str) -> Self:
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel transfer in status {self.status.value}")

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.CANCELLED
        new_transfer.description = f"{self.description}\nCancelled: {reason}"
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("CANCEL", str(cancelled_by), {"reason": reason})
        return new_transfer

    def reverse(self, reversed_by: UUID, reason: str) -> Self:
        if not self.can_reverse():
            raise ValueError(f"Cannot reverse transfer in status {self.status.value}")

        # Create reversal transfer
        reversal = self._create_reversal(reversed_by, reason)

        new_transfer = self._copy()
        new_transfer.status = TransferStatus.REVERSED
        new_transfer.reversed_at = datetime.now(UTC)
        new_transfer.reversed_by = reversed_by
        new_transfer.reversal_reason = reason
        new_transfer.reversal_transfer_id = reversal.transfer_id
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("REVERSE", str(reversed_by), {"reason": reason})
        return new_transfer

    def _create_reversal(self, reversed_by: UUID, reason: str) -> BankTransferEntity:
        """Create reversal transfer."""
        return BankTransferEntity(
            transfer_id=uuid4(),
            transfer_number=f"REV_{self.transfer_number}",
            transfer_type=self.transfer_type,
            from_account_id=self.to_account_id if self.to_account_id else UUID(int=0),
            from_account_number=self.to_account_number,
            to_account_id=self.from_account_id,
            to_account_number=self.from_account_number,
            to_bank_code=self.to_bank_code,
            to_bank_name=self.to_bank_name,
            to_account_name=self.from_account_number,
            amount=self.amount,
            currency=self.currency,
            transfer_date=date.today(),
            value_date=None,
            status=TransferStatus.SUBMITTED,
            priority=self.priority,
            reference=f"REV_{self.reference}" if self.reference else None,
            description=f"Reversal of {self.transfer_number}: {reason}",
            fee_config=self.fee_config,
            legal_entity_id=self.legal_entity_id,
            created_by=reversed_by,
            created_at=datetime.now(UTC),
            version=1,
        )

    # ==================== 2FA Methods ====================

    def require_two_factor(self, required_by: UUID) -> Self:
        new_transfer = self._copy()
        new_transfer.requires_two_factor = True
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("REQUIRE_2FA", str(required_by), {})
        return new_transfer

    def verify_two_factor(self, verified_by: UUID) -> Self:
        if not self.requires_two_factor:
            raise ValueError("Transfer does not require two-factor verification")

        new_transfer = self._copy()
        new_transfer.two_factor_verified_at = datetime.now(UTC)
        new_transfer.two_factor_verified_by = verified_by
        new_transfer.requires_two_factor = False
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("VERIFY_2FA", str(verified_by), {})
        return new_transfer

    # ==================== Signing Methods ====================

    def sign(self, signed_by: str) -> Self:
        new_transfer = self._copy()
        new_transfer.signature = TransferSignature.create(self, signed_by)
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit("SIGN", signed_by, {})
        return new_transfer

    def verify_signature(self) -> bool:
        if not self.signature:
            return False
        return self.signature.verify(self)

    # ==================== Scheduling Methods ====================

    def schedule(self, scheduled_date: date, scheduled_by: UUID) -> Self:
        if scheduled_date < date.today():
            raise ValueError("Scheduled date cannot be in the past")

        new_transfer = self._copy()
        new_transfer.scheduled_date = scheduled_date
        new_transfer.scheduled_by = scheduled_by
        new_transfer.updated_at = datetime.now(UTC)
        new_transfer.version = self.version + 1
        new_transfer._record_audit(
            "SCHEDULE", str(scheduled_by), {"date": scheduled_date.isoformat()}
        )
        return new_transfer

    def is_scheduled(self) -> bool:
        return self.scheduled_date is not None and self.status == TransferStatus.PENDING

    def is_due(self) -> bool:
        return self.is_scheduled() and self.scheduled_date <= date.today()

    # ==================== Private Helpers ====================

    def _copy(self) -> Self:
        return BankTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            transfer_type=self.transfer_type,
            from_account_id=self.from_account_id,
            from_account_number=self.from_account_number,
            to_account_id=self.to_account_id,
            to_account_number=self.to_account_number,
            to_bank_code=self.to_bank_code,
            to_bank_name=self.to_bank_name,
            to_account_name=self.to_account_name,
            amount=self.amount,
            currency=self.currency,
            transfer_date=self.transfer_date,
            value_date=self.value_date,
            status=self.status,
            priority=self.priority,
            reference=self.reference,
            description=self.description,
            fee_config=self.fee_config,
            fee_amount=self.fee_amount,
            fee_currency=self.fee_currency,
            approval_level_required=self.approval_level_required,
            current_approval_level=self.current_approval_level,
            approval_history=self.approval_history.copy(),
            submitted_by=self.submitted_by,
            submitted_at=self.submitted_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejection_reason=self.rejection_reason,
            processed_by=self.processed_by,
            processed_at=self.processed_at,
            failure_reason=self.failure_reason,
            failure_code=self.failure_code,
            reversed_at=self.reversed_at,
            reversed_by=self.reversed_by,
            reversal_reason=self.reversal_reason,
            reversal_transfer_id=self.reversal_transfer_id,
            scheduled_date=self.scheduled_date,
            scheduled_by=self.scheduled_by,
            legal_entity_id=self.legal_entity_id,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            version=self.version,
            signature=self.signature,
            requires_two_factor=self.requires_two_factor,
            two_factor_verified_at=self.two_factor_verified_at,
            two_factor_verified_by=self.two_factor_verified_by,
        )


# ============================================================================
# Alias for Service Layer
# ============================================================================

BankTransfer = BankTransferEntity


# ============================================================================
# Repository Interface (Real Implementation)
# ============================================================================


class BankTransferRepository:
    """Repository for BankTransfer with in-memory storage."""

    _storage: ClassVar[dict[UUID, dict[UUID, BankTransferEntity]]] = {}
    _storage_by_account: ClassVar[dict[UUID, dict[UUID, list[BankTransferEntity]]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, BankTransferEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    async def get_by_id(
        self, transfer_id: UUID, legal_entity_id: UUID
    ) -> BankTransferEntity | None:
        storage = self._get_storage(legal_entity_id)
        return storage.get(transfer_id)

    async def get_by_number(
        self, transfer_number: str, legal_entity_id: UUID
    ) -> BankTransferEntity | None:
        storage = self._get_storage(legal_entity_id)
        for transfer in storage.values():
            if transfer.transfer_number == transfer_number:
                return transfer
        return None

    async def get_by_account(
        self,
        account_id: UUID,
        legal_entity_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[BankTransferEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [
            tx
            for tx in storage.values()
            if tx.from_account_id == account_id or tx.to_account_id == account_id
        ]
        if from_date:
            result = [tx for tx in result if tx.transfer_date >= from_date]
        if to_date:
            result = [tx for tx in result if tx.transfer_date <= to_date]
        result.sort(key=lambda x: x.transfer_date, reverse=True)
        return result

    async def get_pending(self, legal_entity_id: UUID) -> list[BankTransferEntity]:
        storage = self._get_storage(legal_entity_id)
        return [tx for tx in storage.values() if tx.status == TransferStatus.PENDING]

    async def get_by_status(
        self, status: TransferStatus, legal_entity_id: UUID
    ) -> list[BankTransferEntity]:
        storage = self._get_storage(legal_entity_id)
        return [tx for tx in storage.values() if tx.status == status]

    async def get_scheduled(self, legal_entity_id: UUID) -> list[BankTransferEntity]:
        storage = self._get_storage(legal_entity_id)
        return [
            tx
            for tx in storage.values()
            if tx.scheduled_date and tx.status == TransferStatus.PENDING
        ]

    async def count(self, legal_entity_id: UUID, account_id: UUID | None = None) -> int:
        storage = self._get_storage(legal_entity_id)
        if account_id:
            return len(
                [
                    tx
                    for tx in storage.values()
                    if tx.from_account_id == account_id or tx.to_account_id == account_id
                ]
            )
        return len(storage)

    async def save(self, transfer: BankTransferEntity, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        storage[transfer.transfer_id] = transfer

    async def update(self, transfer: BankTransferEntity, legal_entity_id: UUID) -> None:
        await self.save(transfer, legal_entity_id)

    async def delete(self, transfer_id: UUID, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        if transfer_id in storage:
            del storage[transfer_id]

    async def clear(self, legal_entity_id: UUID) -> None:
        if legal_entity_id in self._storage:
            self._storage[legal_entity_id] = {}


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "BankTransfer",
    "BankTransferEntity",
    "BankTransferRepository",
    "TransferFee",
    "TransferPriority",
    "TransferSignature",
    "TransferStatus",
    "TransferType",
]