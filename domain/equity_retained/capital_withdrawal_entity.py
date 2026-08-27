#!/usr/bin/env python3
"""
Module: capital_withdrawal_entity.py
Layer: Domain / Equity & Retained Earnings
Responsibility: Entity untuk capital withdrawal (penarikan modal) dengan semua method entity dasar.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class WithdrawalType(Enum):
    DIVIDEND = "dividend"
    CAPITAL_REDUCTION = "reduction"
    SHARE_BUYBACK = "buyback"
    PARTIAL_WITHDRAWAL = "partial"
    LIQUIDATION = "liquidation"
    REVALUATION_DECREASE = "revaluation_decrease"

    def display_name(self) -> str:
        names = {
            WithdrawalType.DIVIDEND: "Dividen",
            WithdrawalType.CAPITAL_REDUCTION: "Pengurangan Modal",
            WithdrawalType.SHARE_BUYBACK: "Pembelian Kembali Saham",
            WithdrawalType.PARTIAL_WITHDRAWAL: "Penarikan Sebagian",
            WithdrawalType.LIQUIDATION: "Distribusi Likuidasi",
            WithdrawalType.REVALUATION_DECREASE: "Penurunan Revaluasi",
        }
        return names.get(self, self.value)


class WithdrawalStatus(Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    POSTED = "posted"
    CANCELLED = "cancelled"

    def can_edit(self) -> bool:
        return self == WithdrawalStatus.DRAFT

    def can_approve(self) -> bool:
        return self == WithdrawalStatus.DRAFT

    def can_post(self) -> bool:
        return self == WithdrawalStatus.APPROVED

    def can_cancel(self) -> bool:
        return self in (WithdrawalStatus.DRAFT, WithdrawalStatus.APPROVED)

    def display_name(self) -> str:
        names = {
            WithdrawalStatus.DRAFT: "Draft",
            WithdrawalStatus.APPROVED: "Disetujui",
            WithdrawalStatus.POSTED: "Diposting",
            WithdrawalStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)


# ============================================================================
# Custom Exceptions
# ============================================================================


class CapitalWithdrawalError(ValueError):
    pass


class InvalidWithdrawalAmountError(CapitalWithdrawalError):
    pass


class WithdrawalExceedsCapitalError(CapitalWithdrawalError):
    pass


class InvalidStatusTransitionError(CapitalWithdrawalError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_withdrawal_number(number: str) -> str:
    if not number or not isinstance(number, str):
        raise CapitalWithdrawalError("Withdrawal number must be a non-empty string")
    cleaned = number.strip()
    if len(cleaned) < 3:
        raise CapitalWithdrawalError("Withdrawal number must be at least 3 characters")
    if len(cleaned) > 30:
        raise CapitalWithdrawalError("Withdrawal number must not exceed 30 characters")
    if not re.match(r"^[A-Za-z0-9\-_/]+$", cleaned):
        raise CapitalWithdrawalError(
            "Withdrawal number can only contain letters, numbers, hyphens, underscores, and slashes"
        )
    return cleaned


def _validate_amount(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount))
        except Exception:
            raise InvalidWithdrawalAmountError(f"Invalid amount type: {type(amount)}")
    if amount <= 0:
        raise InvalidWithdrawalAmountError(f"Withdrawal amount must be positive: {amount}")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_currency(currency: str) -> str:
    if not currency or not isinstance(currency, str):
        raise CapitalWithdrawalError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise CapitalWithdrawalError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise CapitalWithdrawalError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


# ============================================================================
# Entity: CapitalWithdrawalEntity
# ============================================================================


@dataclass
class CapitalWithdrawalEntity:
    withdrawal_id: UUID
    legal_entity_id: UUID
    withdrawal_number: str
    withdrawal_type: WithdrawalType
    shareholder_id: UUID
    shareholder_name: str
    amount: Decimal
    currency: str
    withdrawal_date: datetime
    status: WithdrawalStatus
    description: str = ""
    approval_reference: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    posted_by: str | None = None
    posted_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    tax_withheld_amount: Decimal = Decimal("0")
    bank_account_reference: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        # Validate withdrawal_number
        normalized_number = _validate_withdrawal_number(self.withdrawal_number)
        if normalized_number != self.withdrawal_number:
            object.__setattr__(self, "withdrawal_number", normalized_number)

        # Validate withdrawal_type
        if not isinstance(self.withdrawal_type, WithdrawalType):
            raise CapitalWithdrawalError(f"Invalid withdrawal_type: {self.withdrawal_type}")

        # Validate shareholder_name
        if not self.shareholder_name or not isinstance(self.shareholder_name, str):
            raise CapitalWithdrawalError("Shareholder name must be a non-empty string")
        name_clean = self.shareholder_name.strip()
        if len(name_clean) < 2:
            raise CapitalWithdrawalError("Shareholder name must be at least 2 characters")
        if len(name_clean) > 200:
            raise CapitalWithdrawalError("Shareholder name must not exceed 200 characters")
        object.__setattr__(self, "shareholder_name", name_clean)

        # Validate amount
        normalized_amount = _validate_amount(self.amount)
        if normalized_amount != self.amount:
            object.__setattr__(self, "amount", normalized_amount)

        # Validate tax_withheld_amount
        if not isinstance(self.tax_withheld_amount, Decimal):
            object.__setattr__(self, "tax_withheld_amount", Decimal(str(self.tax_withheld_amount)))
        if self.tax_withheld_amount < 0:
            raise CapitalWithdrawalError(
                f"Tax withheld amount cannot be negative: {self.tax_withheld_amount}"
            )
        if self.tax_withheld_amount > self.amount:
            raise CapitalWithdrawalError(
                f"Tax withheld amount {self.tax_withheld_amount} exceeds withdrawal amount {self.amount}"
            )

        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Validate withdrawal_date UTC
        if self.withdrawal_date.tzinfo is None:
            object.__setattr__(self, "withdrawal_date", self.withdrawal_date.replace(tzinfo=UTC))

        # Validate status
        if not isinstance(self.status, WithdrawalStatus):
            raise CapitalWithdrawalError(f"Invalid status: {self.status}")

        # Validate approval dates
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.posted_at and self.posted_at.tzinfo is None:
            object.__setattr__(self, "posted_at", self.posted_at.replace(tzinfo=UTC))
        if self.cancelled_at and self.cancelled_at.tzinfo is None:
            object.__setattr__(self, "cancelled_at", self.cancelled_at.replace(tzinfo=UTC))

        # Validate status consistency
        if self.status == WithdrawalStatus.APPROVED and not self.approved_by:
            raise CapitalWithdrawalError("Approved withdrawal must have approved_by")
        if self.status == WithdrawalStatus.POSTED and not self.posted_by:
            raise CapitalWithdrawalError("Posted withdrawal must have posted_by")
        if self.status == WithdrawalStatus.CANCELLED and not self.cancelled_by:
            raise CapitalWithdrawalError("Cancelled withdrawal must have cancelled_by")

        # Validate timestamps UTC
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise CapitalWithdrawalError("Version must be >= 1")

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "withdrawal_id": str(self.withdrawal_id),
            "number": self.withdrawal_number,
            "shareholder": self.shareholder_name,
            "amount": str(self.amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "withdrawal_id": str(self.withdrawal_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> CapitalWithdrawalEntity:
        self._record_audit(
            "CREATE", created_by, {"number": self.withdrawal_number, "amount": str(self.amount)}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> CapitalWithdrawalEntity:
        if not self.status.can_edit():
            raise InvalidStatusTransitionError(
                f"Cannot update withdrawal in status {self.status.value}"
            )
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("withdrawal_id", "created_at", "created_by", "version"):
                data[key] = value
        new_entity = self.from_dict(data)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = updated_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entity

    def delete(self, deleted_by: str, reason: str | None = None) -> CapitalWithdrawalEntity:
        if self.status not in (WithdrawalStatus.DRAFT, WithdrawalStatus.CANCELLED):
            raise InvalidStatusTransitionError(
                f"Cannot delete withdrawal in status {self.status.value}"
            )
        new_entity = self.cancel(deleted_by, reason or "Deleted by user")
        new_entity._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entity

    def restore(self, restored_by: str) -> CapitalWithdrawalEntity:
        if self.status != WithdrawalStatus.CANCELLED:
            raise InvalidStatusTransitionError(
                f"Cannot restore withdrawal in status {self.status.value}"
            )
        new_entity = self._copy()
        new_entity.status = WithdrawalStatus.DRAFT
        new_entity.cancelled_by = None
        new_entity.cancelled_at = None
        new_entity.cancel_reason = ""
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = restored_by
        new_entity.version = self.version + 1
        new_entity._record_audit("RESTORE", restored_by, {})
        return new_entity

    def activate(self, activated_by: str) -> CapitalWithdrawalEntity:
        if self.status != WithdrawalStatus.DRAFT:
            raise InvalidStatusTransitionError(
                f"Cannot activate withdrawal in status {self.status.value}"
            )
        return self.approve(activated_by)

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CapitalWithdrawalEntity:
        if self.status != WithdrawalStatus.DRAFT:
            raise InvalidStatusTransitionError(
                f"Cannot deactivate withdrawal in status {self.status.value}"
            )
        return self.cancel(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: str, reason: str) -> CapitalWithdrawalEntity:
        new_entity = self._copy()
        new_entity.metadata["locked_by"] = locked_by
        new_entity.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_entity.metadata["lock_reason"] = reason
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = locked_by
        new_entity.version = self.version + 1
        new_entity._record_audit("LOCK", locked_by, {"reason": reason})
        return new_entity

    def unlock(self, unlocked_by: str) -> CapitalWithdrawalEntity:
        new_entity = self._copy()
        new_entity.metadata.pop("locked_by", None)
        new_entity.metadata.pop("locked_at", None)
        new_entity.metadata.pop("lock_reason", None)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = unlocked_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UNLOCK", unlocked_by, {})
        return new_entity

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except CapitalWithdrawalError as e:
            errors.append(str(e))
        if self.status == WithdrawalStatus.POSTED and self.posted_at is None:
            errors.append("Posted status requires posted_at")
        if self.status == WithdrawalStatus.APPROVED and self.approved_at is None:
            errors.append("Approved status requires approved_at")
        if self.tax_withheld_amount > self.amount:
            errors.append(
                f"Tax withheld amount {self.tax_withheld_amount} exceeds withdrawal amount {self.amount}"
            )
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "withdrawal_id": str(self.withdrawal_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "withdrawal_id": str(self.withdrawal_id),
            "legal_entity_id": str(self.legal_entity_id),
            "withdrawal_number": self.withdrawal_number,
            "withdrawal_type": self.withdrawal_type.value,
            "shareholder_id": str(self.shareholder_id),
            "shareholder_name": self.shareholder_name,
            "amount": str(self.amount),
            "currency": self.currency,
            "withdrawal_date": self.withdrawal_date.isoformat(),
            "status": self.status.value,
            "description": self.description,
            "approval_reference": self.approval_reference,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "posted_by": self.posted_by,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "tax_withheld_amount": str(self.tax_withheld_amount),
            "bank_account_reference": self.bank_account_reference,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapitalWithdrawalEntity:
        withdrawal_type = WithdrawalType(data["withdrawal_type"])
        status = WithdrawalStatus(data["status"])
        withdrawal_date = datetime.fromisoformat(data["withdrawal_date"])
        approved_at = (
            datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None
        )
        posted_at = datetime.fromisoformat(data["posted_at"]) if data.get("posted_at") else None
        cancelled_at = (
            datetime.fromisoformat(data["cancelled_at"]) if data.get("cancelled_at") else None
        )
        return cls(
            withdrawal_id=UUID(data["withdrawal_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            withdrawal_number=data["withdrawal_number"],
            withdrawal_type=withdrawal_type,
            shareholder_id=UUID(data["shareholder_id"]),
            shareholder_name=data["shareholder_name"],
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            withdrawal_date=withdrawal_date,
            status=status,
            description=data.get("description", ""),
            approval_reference=data.get("approval_reference"),
            approved_by=data.get("approved_by"),
            approved_at=approved_at,
            posted_by=data.get("posted_by"),
            posted_at=posted_at,
            cancelled_by=data.get("cancelled_by"),
            cancelled_at=cancelled_at,
            cancel_reason=data.get("cancel_reason", ""),
            tax_withheld_amount=Decimal(data.get("tax_withheld_amount", "0")),
            bank_account_reference=data.get("bank_account_reference"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self, new_number: str | None = None) -> CapitalWithdrawalEntity:
        new_id = uuid4()
        new_number_str = new_number or f"{self.withdrawal_number}_COPY"
        now = datetime.now(UTC)
        cloned = CapitalWithdrawalEntity(
            withdrawal_id=new_id,
            legal_entity_id=self.legal_entity_id,
            withdrawal_number=new_number_str,
            withdrawal_type=self.withdrawal_type,
            shareholder_id=self.shareholder_id,
            shareholder_name=self.shareholder_name,
            amount=self.amount,
            currency=self.currency,
            withdrawal_date=self.withdrawal_date,
            status=WithdrawalStatus.DRAFT,
            description=f"Cloned from {self.withdrawal_number}",
            tax_withheld_amount=self.tax_withheld_amount,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            updated_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.withdrawal_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "withdrawal_id": str(self.withdrawal_id),
            "number": self.withdrawal_number,
            "amount": str(self.amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CapitalWithdrawalEntity:
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = touched_by
        new_entity.version = self.version + 1
        new_entity._record_audit("TOUCH", touched_by, {})
        return new_entity

    # ==================== PROPERTIES ====================

    @property
    def net_amount(self) -> Decimal:
        return self.amount - self.tax_withheld_amount

    @property
    def is_draft(self) -> bool:
        return self.status == WithdrawalStatus.DRAFT

    @property
    def is_approved(self) -> bool:
        return self.status == WithdrawalStatus.APPROVED

    @property
    def is_posted(self) -> bool:
        return self.status == WithdrawalStatus.POSTED

    @property
    def is_cancelled(self) -> bool:
        return self.status == WithdrawalStatus.CANCELLED

    @property
    def can_edit(self) -> bool:
        return self.status.can_edit()

    @property
    def can_approve(self) -> bool:
        return self.status.can_approve()

    @property
    def can_post(self) -> bool:
        return self.status.can_post()

    @property
    def can_cancel(self) -> bool:
        return self.status.can_cancel()

    # ==================== BUSINESS LOGIC ====================

    def approve(
        self, approved_by: str, approval_reference: str | None = None
    ) -> CapitalWithdrawalEntity:
        if not self.can_approve:
            raise InvalidStatusTransitionError(
                f"Cannot approve withdrawal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = WithdrawalStatus.APPROVED
        new_entity.approved_by = approved_by
        new_entity.approved_at = now
        if approval_reference:
            new_entity.approval_reference = approval_reference
        new_entity.updated_at = now
        new_entity.updated_by = approved_by
        new_entity.version = self.version + 1
        new_entity._record_audit("APPROVE", approved_by, {"reference": approval_reference})
        return new_entity

    def post(self, posted_by: str) -> CapitalWithdrawalEntity:
        if not self.can_post:
            raise InvalidStatusTransitionError(
                f"Cannot post withdrawal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = WithdrawalStatus.POSTED
        new_entity.posted_by = posted_by
        new_entity.posted_at = now
        new_entity.updated_at = now
        new_entity.updated_by = posted_by
        new_entity.version = self.version + 1
        new_entity._record_audit("POST", posted_by, {})
        return new_entity

    def cancel(self, cancelled_by: str, reason: str) -> CapitalWithdrawalEntity:
        if not self.can_cancel:
            raise InvalidStatusTransitionError(
                f"Cannot cancel withdrawal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = WithdrawalStatus.CANCELLED
        new_entity.cancelled_by = cancelled_by
        new_entity.cancelled_at = now
        new_entity.cancel_reason = reason
        new_entity.updated_at = now
        new_entity.updated_by = cancelled_by
        new_entity.version = self.version + 1
        new_entity._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_entity

    def update_description(self, new_description: str, updated_by: str) -> CapitalWithdrawalEntity:
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit withdrawal in status {self.status.value}"
            )
        new_entity = self._copy()
        new_entity.description = new_description
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = updated_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE_DESCRIPTION", updated_by, {})
        return new_entity

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> CapitalWithdrawalEntity:
        return CapitalWithdrawalEntity(
            withdrawal_id=self.withdrawal_id,
            legal_entity_id=self.legal_entity_id,
            withdrawal_number=self.withdrawal_number,
            withdrawal_type=self.withdrawal_type,
            shareholder_id=self.shareholder_id,
            shareholder_name=self.shareholder_name,
            amount=self.amount,
            currency=self.currency,
            withdrawal_date=self.withdrawal_date,
            status=self.status,
            description=self.description,
            approval_reference=self.approval_reference,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            tax_withheld_amount=self.tax_withheld_amount,
            bank_account_reference=self.bank_account_reference,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class CapitalWithdrawalRepository:
    _storage: ClassVar[dict[UUID, dict[UUID, CapitalWithdrawalEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, CapitalWithdrawalEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    async def get_by_id(
        cls, withdrawal_id: UUID, legal_entity_id: UUID
    ) -> CapitalWithdrawalEntity | None:
        storage = cls._get_storage(legal_entity_id)
        return storage.get(withdrawal_id)

    @classmethod
    async def get_by_number(
        cls, withdrawal_number: str, legal_entity_id: UUID
    ) -> CapitalWithdrawalEntity | None:
        storage = cls._get_storage(legal_entity_id)
        for w in storage.values():
            if w.withdrawal_number == withdrawal_number:
                return w
        return None

    @classmethod
    async def get_by_shareholder(
        cls, shareholder_id: UUID, legal_entity_id: UUID, limit: int = 100
    ) -> list[CapitalWithdrawalEntity]:
        storage = cls._get_storage(legal_entity_id)
        return [w for w in storage.values() if w.shareholder_id == shareholder_id][:limit]

    @classmethod
    async def get_by_status(
        cls, status: WithdrawalStatus, legal_entity_id: UUID, limit: int = 100
    ) -> list[CapitalWithdrawalEntity]:
        storage = cls._get_storage(legal_entity_id)
        return [w for w in storage.values() if w.status == status][:limit]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[CapitalWithdrawalEntity]:
        storage = cls._get_storage(legal_entity_id)
        return list(storage.values())

    @classmethod
    async def save(cls, withdrawal: CapitalWithdrawalEntity, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage[withdrawal.withdrawal_id] = withdrawal

    @classmethod
    async def update(cls, withdrawal: CapitalWithdrawalEntity, legal_entity_id: UUID) -> None:
        await cls.save(withdrawal, legal_entity_id)

    @classmethod
    async def delete(cls, withdrawal_id: UUID, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage.pop(withdrawal_id, None)

    @classmethod
    async def exists(cls, withdrawal_id: UUID, legal_entity_id: UUID) -> bool:
        storage = cls._get_storage(legal_entity_id)
        return withdrawal_id in storage

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        storage = cls._get_storage(legal_entity_id)
        return len(storage)

    @classmethod
    async def list(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CapitalWithdrawalEntity]:
        withdrawals = await cls.get_all(legal_entity_id)
        return withdrawals[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[CapitalWithdrawalEntity], int]:
        withdrawals = await cls.get_all(legal_entity_id)
        total = len(withdrawals)
        start = (page - 1) * per_page
        end = start + per_page
        return withdrawals[start:end], total

    @classmethod
    async def search(
        cls, legal_entity_id: UUID, query: str, fields: list[str] | None = None
    ) -> list[CapitalWithdrawalEntity]:
        if fields is None:
            fields = ["withdrawal_number", "shareholder_name", "description"]
        withdrawals = await cls.get_all(legal_entity_id)
        query_lower = query.lower()
        results = []
        for w in withdrawals:
            for field_name in fields:  # F402 fix: renamed from 'field' to 'field_name'
                value = getattr(w, field_name, "")
                if value and query_lower in str(value).lower():
                    results.append(w)
                    break
        return results

    @classmethod
    async def lock(
        cls, withdrawal_id: UUID, legal_entity_id: UUID, locked_by: str, reason: str
    ) -> CapitalWithdrawalEntity:
        w = await cls.get_by_id(withdrawal_id, legal_entity_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        locked = w.lock(locked_by, reason)
        await cls.save(locked, legal_entity_id)
        return locked

    @classmethod
    async def unlock(
        cls, withdrawal_id: UUID, legal_entity_id: UUID, unlocked_by: str
    ) -> CapitalWithdrawalEntity:
        w = await cls.get_by_id(withdrawal_id, legal_entity_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        unlocked = w.unlock(unlocked_by)
        await cls.save(unlocked, legal_entity_id)
        return unlocked

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        if legal_entity_id in cls._storage:
            cls._storage[legal_entity_id] = {}


__all__ = [
    "CapitalWithdrawalEntity",
    "CapitalWithdrawalError",
    "CapitalWithdrawalRepository",
    "InvalidStatusTransitionError",
    "InvalidWithdrawalAmountError",
    "WithdrawalExceedsCapitalError",
    "WithdrawalStatus",
    "WithdrawalType",
]
