#!/usr/bin/env python3
"""
Module: dividend_declaration_entity.py
Layer: Domain / Equity & Retained Earnings
Responsibility: Entity untuk dividend declaration (deklarasi dividen) dengan semua method entity dasar.
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


class DividendType(Enum):
    CASH = "cash"
    STOCK = "stock"
    PROPERTY = "property"

    def display_name(self) -> str:
        names = {
            DividendType.CASH: "Dividen Tunai",
            DividendType.STOCK: "Dividen Saham",
            DividendType.PROPERTY: "Dividen Properti",
        }
        return names.get(self, self.value)


class DividendStatus(Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    CANCELLED = "cancelled"

    def can_approve(self) -> bool:
        return self == DividendStatus.PROPOSED

    def can_pay(self) -> bool:
        return self in (DividendStatus.APPROVED, DividendStatus.PARTIALLY_PAID)

    def can_cancel(self) -> bool:
        return self in (DividendStatus.PROPOSED, DividendStatus.APPROVED)

    def can_edit(self) -> bool:
        return self == DividendStatus.PROPOSED

    def display_name(self) -> str:
        names = {
            DividendStatus.PROPOSED: "Diusulkan",
            DividendStatus.APPROVED: "Disetujui",
            DividendStatus.PAID: "Dibayar",
            DividendStatus.PARTIALLY_PAID: "Sebagian Dibayar",
            DividendStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)


# ============================================================================
# Value Object: DividendShareholderAllocation
# ============================================================================


@dataclass(frozen=True)
class DividendShareholderAllocation:
    shareholder_id: UUID
    shareholder_name: str
    shares_owned: Decimal
    share_percentage: Decimal
    dividend_amount: Decimal
    paid_amount: Decimal = Decimal("0")
    paid_at: datetime | None = None
    payment_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.shareholder_name or len(self.shareholder_name.strip()) < 2:
            raise ValueError("Shareholder name must be at least 2 characters")
        if self.shares_owned <= 0:
            raise ValueError(f"Shares owned must be positive: {self.shares_owned}")
        if self.share_percentage < 0 or self.share_percentage > 100:
            raise ValueError(f"Share percentage must be 0-100: {self.share_percentage}")
        if self.dividend_amount <= 0:
            raise ValueError(f"Dividend amount must be positive: {self.dividend_amount}")
        if self.paid_amount < 0:
            raise ValueError(f"Paid amount cannot be negative: {self.paid_amount}")
        if self.paid_amount > self.dividend_amount:
            raise ValueError(
                f"Paid amount {self.paid_amount} exceeds dividend amount {self.dividend_amount}"
            )
        if self.paid_at and self.paid_at.tzinfo is None:
            object.__setattr__(self, "paid_at", self.paid_at.replace(tzinfo=UTC))

    @property
    def remaining_amount(self) -> Decimal:
        return self.dividend_amount - self.paid_amount

    @property
    def is_fully_paid(self) -> bool:
        return self.remaining_amount == 0

    @property
    def payment_completion_percentage(self) -> Decimal:
        if self.dividend_amount == 0:
            return Decimal("0")
        return (self.paid_amount / self.dividend_amount * Decimal("100")).quantize(Decimal("0.01"))

    def record_payment(
        self, amount: Decimal, paid_at: datetime | None = None, reference: str | None = None
    ) -> DividendShareholderAllocation:
        new_paid = self.paid_amount + amount
        if new_paid > self.dividend_amount:
            raise ValueError(
                f"Payment amount {amount} would exceed remaining {self.remaining_amount}"
            )
        if paid_at is None:
            paid_at = datetime.now(UTC)
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=UTC)
        return DividendShareholderAllocation(
            shareholder_id=self.shareholder_id,
            shareholder_name=self.shareholder_name,
            shares_owned=self.shares_owned,
            share_percentage=self.share_percentage,
            dividend_amount=self.dividend_amount,
            paid_amount=new_paid,
            paid_at=paid_at,
            payment_reference=reference or self.payment_reference,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "shareholder_id": str(self.shareholder_id),
            "shareholder_name": self.shareholder_name,
            "shares_owned": str(self.shares_owned),
            "share_percentage": str(self.share_percentage),
            "dividend_amount": str(self.dividend_amount),
            "paid_amount": str(self.paid_amount),
            "remaining_amount": str(self.remaining_amount),
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "payment_reference": self.payment_reference,
            "is_fully_paid": self.is_fully_paid,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DividendShareholderAllocation:
        paid_at = data.get("paid_at")
        if isinstance(paid_at, str):
            paid_at = datetime.fromisoformat(paid_at)
        return cls(
            shareholder_id=UUID(data["shareholder_id"]),
            shareholder_name=data["shareholder_name"],
            shares_owned=Decimal(data["shares_owned"]),
            share_percentage=Decimal(data["share_percentage"]),
            dividend_amount=Decimal(data["dividend_amount"]),
            paid_amount=Decimal(data.get("paid_amount", "0")),
            paid_at=paid_at,
            payment_reference=data.get("payment_reference"),
        )


# ============================================================================
# Custom Exceptions
# ============================================================================


class DividendError(ValueError):
    pass


class InvalidDividendAmountError(DividendError):
    pass


class InvalidDividendDatesError(DividendError):
    pass


class AllocationMismatchError(DividendError):
    pass


class InvalidStatusTransitionError(DividendError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_dividend_number(number: str) -> str:
    if not number or not isinstance(number, str):
        raise DividendError("Dividend number must be a non-empty string")
    cleaned = number.strip()
    if len(cleaned) < 3:
        raise DividendError("Dividend number must be at least 3 characters")
    if len(cleaned) > 30:
        raise DividendError("Dividend number must not exceed 30 characters")
    if not re.match(r"^[A-Za-z0-9\-_/]+$", cleaned):
        raise DividendError(
            "Dividend number can only contain letters, numbers, hyphens, underscores, and slashes"
        )
    return cleaned


def _validate_amount(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount))
        except Exception:
            raise InvalidDividendAmountError(f"Invalid amount type: {type(amount)}")
    if amount <= 0:
        raise InvalidDividendAmountError(f"Dividend amount must be positive: {amount}")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_currency(currency: str) -> str:
    if not currency or not isinstance(currency, str):
        raise DividendError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise DividendError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise DividendError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


def _validate_dates(
    declaration_date: datetime, record_date: datetime, payment_date: datetime
) -> None:
    if record_date <= declaration_date:
        raise InvalidDividendDatesError(
            f"Record date {record_date} must be after declaration date {declaration_date}"
        )
    if payment_date <= record_date:
        raise InvalidDividendDatesError(
            f"Payment date {payment_date} must be after record date {record_date}"
        )


def _validate_allocations(
    allocations: list[DividendShareholderAllocation], total_amount: Decimal
) -> None:
    if not allocations:
        return
    total_allocated = sum(a.dividend_amount for a in allocations)
    if total_allocated != total_amount:
        raise AllocationMismatchError(
            f"Total allocated {total_allocated} does not equal total dividend amount {total_amount}"
        )


# ============================================================================
# Entity: DividendDeclarationEntity
# ============================================================================


@dataclass
class DividendDeclarationEntity:
    dividend_id: UUID
    legal_entity_id: UUID
    dividend_number: str
    dividend_type: DividendType
    declaration_date: datetime
    record_date: datetime
    payment_date: datetime
    total_amount: Decimal
    currency: str
    status: DividendStatus
    description: str = ""
    resolution_reference: str | None = None
    allocations: list[DividendShareholderAllocation] = field(default_factory=list)
    approved_by: str | None = None
    approved_at: datetime | None = None
    paid_by: str | None = None
    paid_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
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
        normalized_number = _validate_dividend_number(self.dividend_number)
        if normalized_number != self.dividend_number:
            object.__setattr__(self, "dividend_number", normalized_number)

        if not isinstance(self.dividend_type, DividendType):
            raise DividendError(f"Invalid dividend_type: {self.dividend_type}")

        for dt_field in ["declaration_date", "record_date", "payment_date"]:
            dt = getattr(self, dt_field)
            if dt.tzinfo is None:
                object.__setattr__(self, dt_field, dt.replace(tzinfo=UTC))
        _validate_dates(self.declaration_date, self.record_date, self.payment_date)

        normalized_amount = _validate_amount(self.total_amount)
        if normalized_amount != self.total_amount:
            object.__setattr__(self, "total_amount", normalized_amount)

        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        if not isinstance(self.status, DividendStatus):
            raise DividendError(f"Invalid status: {self.status}")

        if self.allocations:
            _validate_allocations(self.allocations, self.total_amount)

        if self.status == DividendStatus.APPROVED and not self.approved_by:
            raise DividendError("Approved dividend must have approved_by")
        if self.status == DividendStatus.PAID and not self.paid_by:
            raise DividendError("Paid dividend must have paid_by")
        if self.status == DividendStatus.CANCELLED and not self.cancelled_by:
            raise DividendError("Cancelled dividend must have cancelled_by")

        for ts_field in ["approved_at", "paid_at", "cancelled_at", "created_at", "updated_at"]:
            ts = getattr(self, ts_field)
            if ts and ts.tzinfo is None:
                object.__setattr__(self, ts_field, ts.replace(tzinfo=UTC))

        if self.version < 1:
            raise DividendError("Version must be >= 1")

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "dividend_id": str(self.dividend_id),
            "number": self.dividend_number,
            "total_amount": str(self.total_amount),
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
            "dividend_id": str(self.dividend_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> DividendDeclarationEntity:
        self._record_audit(
            "CREATE", created_by, {"number": self.dividend_number, "amount": str(self.total_amount)}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> DividendDeclarationEntity:
        if not self.status.can_edit():
            raise InvalidStatusTransitionError(
                f"Cannot update dividend in status {self.status.value}"
            )
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("dividend_id", "created_at", "created_by", "version"):
                data[key] = value
        new_entity = self.from_dict(data)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = updated_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entity

    def delete(self, deleted_by: str, reason: str | None = None) -> DividendDeclarationEntity:
        if self.status not in (DividendStatus.PROPOSED, DividendStatus.CANCELLED):
            raise InvalidStatusTransitionError(
                f"Cannot delete dividend in status {self.status.value}"
            )
        new_entity = self.cancel(deleted_by, reason or "Deleted by user")
        new_entity._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entity

    def restore(self, restored_by: str) -> DividendDeclarationEntity:
        if self.status != DividendStatus.CANCELLED:
            raise InvalidStatusTransitionError(
                f"Cannot restore dividend in status {self.status.value}"
            )
        new_entity = self._copy()
        new_entity.status = DividendStatus.PROPOSED
        new_entity.cancelled_by = None
        new_entity.cancelled_at = None
        new_entity.cancel_reason = ""
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = restored_by
        new_entity.version = self.version + 1
        new_entity._record_audit("RESTORE", restored_by, {})
        return new_entity

    def activate(self, activated_by: str) -> DividendDeclarationEntity:
        if self.status != DividendStatus.PROPOSED:
            raise InvalidStatusTransitionError(
                f"Cannot activate dividend in status {self.status.value}"
            )
        return self.approve(activated_by)

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> DividendDeclarationEntity:
        if self.status != DividendStatus.PROPOSED:
            raise InvalidStatusTransitionError(
                f"Cannot deactivate dividend in status {self.status.value}"
            )
        return self.cancel(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: str, reason: str) -> DividendDeclarationEntity:
        new_entity = self._copy()
        new_entity.metadata["locked_by"] = locked_by
        new_entity.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_entity.metadata["lock_reason"] = reason
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = locked_by
        new_entity.version = self.version + 1
        new_entity._record_audit("LOCK", locked_by, {"reason": reason})
        return new_entity

    def unlock(self, unlocked_by: str) -> DividendDeclarationEntity:
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
        except DividendError as e:
            errors.append(str(e))
        if self.status == DividendStatus.APPROVED and self.approved_at is None:
            errors.append("Approved status requires approved_at")
        if self.status == DividendStatus.PAID and self.paid_at is None:
            errors.append("Paid status requires paid_at")
        if self.total_paid > self.total_amount:
            errors.append(f"Total paid {self.total_paid} exceeds total amount {self.total_amount}")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "dividend_id": str(self.dividend_id),
            "version": self.version,
        }

    def to_dict(self, include_allocations: bool = True) -> dict[str, Any]:
        result = {
            "dividend_id": str(self.dividend_id),
            "legal_entity_id": str(self.legal_entity_id),
            "dividend_number": self.dividend_number,
            "dividend_type": self.dividend_type.value,
            "declaration_date": self.declaration_date.isoformat(),
            "record_date": self.record_date.isoformat(),
            "payment_date": self.payment_date.isoformat(),
            "total_amount": str(self.total_amount),
            "currency": self.currency,
            "status": self.status.value,
            "description": self.description,
            "resolution_reference": self.resolution_reference,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "paid_by": self.paid_by,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
            "metadata": self.metadata,
            "total_paid": str(self.total_paid),
            "unpaid_amount": str(self.unpaid_amount),
            "payment_completion_percentage": str(self.payment_completion_percentage),
        }
        if include_allocations:
            result["allocations"] = [a.to_dict() for a in self.allocations]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DividendDeclarationEntity:
        dividend_type = DividendType(data["dividend_type"])
        status = DividendStatus(data["status"])
        declaration_date = datetime.fromisoformat(data["declaration_date"])
        record_date = datetime.fromisoformat(data["record_date"])
        payment_date = datetime.fromisoformat(data["payment_date"])
        approved_at = (
            datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None
        )
        paid_at = datetime.fromisoformat(data["paid_at"]) if data.get("paid_at") else None
        cancelled_at = (
            datetime.fromisoformat(data["cancelled_at"]) if data.get("cancelled_at") else None
        )

        allocations = []
        for alloc_data in data.get("allocations", []):
            allocations.append(DividendShareholderAllocation.from_dict(alloc_data))

        return cls(
            dividend_id=UUID(data["dividend_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            dividend_number=data["dividend_number"],
            dividend_type=dividend_type,
            declaration_date=declaration_date,
            record_date=record_date,
            payment_date=payment_date,
            total_amount=Decimal(data["total_amount"]),
            currency=data["currency"],
            status=status,
            description=data.get("description", ""),
            resolution_reference=data.get("resolution_reference"),
            allocations=allocations,
            approved_by=data.get("approved_by"),
            approved_at=approved_at,
            paid_by=data.get("paid_by"),
            paid_at=paid_at,
            cancelled_by=data.get("cancelled_by"),
            cancelled_at=cancelled_at,
            cancel_reason=data.get("cancel_reason", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self, new_number: str | None = None) -> DividendDeclarationEntity:
        new_id = uuid4()
        new_number_str = new_number or f"{self.dividend_number}_COPY"
        now = datetime.now(UTC)
        cloned = DividendDeclarationEntity(
            dividend_id=new_id,
            legal_entity_id=self.legal_entity_id,
            dividend_number=new_number_str,
            dividend_type=self.dividend_type,
            declaration_date=self.declaration_date,
            record_date=self.record_date,
            payment_date=self.payment_date,
            total_amount=self.total_amount,
            currency=self.currency,
            status=DividendStatus.PROPOSED,
            description=f"Cloned from {self.dividend_number}",
            resolution_reference=self.resolution_reference,
            allocations=[a for a in self.allocations],
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            updated_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.dividend_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "dividend_id": str(self.dividend_id),
            "number": self.dividend_number,
            "total_amount": str(self.total_amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DividendDeclarationEntity:
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = touched_by
        new_entity.version = self.version + 1
        new_entity._record_audit("TOUCH", touched_by, {})
        return new_entity

    # ==================== PROPERTIES ====================

    @property
    def total_paid(self) -> Decimal:
        return sum(a.paid_amount for a in self.allocations)

    @property
    def unpaid_amount(self) -> Decimal:
        return self.total_amount - self.total_paid

    @property
    def payment_completion_percentage(self) -> Decimal:
        if self.total_amount == 0:
            return Decimal("0")
        return (self.total_paid / self.total_amount * Decimal("100")).quantize(Decimal("0.01"))

    @property
    def is_proposed(self) -> bool:
        return self.status == DividendStatus.PROPOSED

    @property
    def is_approved(self) -> bool:
        return self.status == DividendStatus.APPROVED

    @property
    def is_paid(self) -> bool:
        return self.status == DividendStatus.PAID

    @property
    def is_partially_paid(self) -> bool:
        return self.status == DividendStatus.PARTIALLY_PAID

    @property
    def is_cancelled(self) -> bool:
        return self.status == DividendStatus.CANCELLED

    @property
    def can_approve(self) -> bool:
        return self.status.can_approve()

    @property
    def can_pay(self) -> bool:
        return self.status.can_pay()

    @property
    def can_cancel(self) -> bool:
        return self.status.can_cancel()

    @property
    def can_edit(self) -> bool:
        return self.status.can_edit()

    # ==================== BUSINESS LOGIC ====================

    def approve(self, approved_by: str) -> DividendDeclarationEntity:
        if not self.can_approve:
            raise InvalidStatusTransitionError(
                f"Cannot approve dividend in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = DividendStatus.APPROVED
        new_entity.approved_by = approved_by
        new_entity.approved_at = now
        new_entity.updated_at = now
        new_entity.updated_by = approved_by
        new_entity.version = self.version + 1
        new_entity._record_audit("APPROVE", approved_by, {})
        return new_entity

    def record_payment(
        self,
        amount: Decimal,
        paid_by: str,
        payment_date: datetime | None = None,
        allocation_filter: UUID | None = None,
    ) -> DividendDeclarationEntity:
        if not self.can_pay:
            raise InvalidStatusTransitionError(
                f"Cannot record payment in status {self.status.value}"
            )
        if amount <= 0:
            raise InvalidDividendAmountError("Payment amount must be positive")
        if amount > self.unpaid_amount:
            raise InvalidDividendAmountError(
                f"Payment amount {amount} exceeds unpaid amount {self.unpaid_amount}"
            )

        if payment_date is None:
            payment_date = datetime.now(UTC)
        if payment_date.tzinfo is None:
            payment_date = payment_date.replace(tzinfo=UTC)

        new_allocations = []
        remaining_to_pay = amount
        for alloc in self.allocations:
            if allocation_filter and alloc.shareholder_id != allocation_filter:
                new_allocations.append(alloc)
                continue
            if remaining_to_pay <= 0:
                new_allocations.append(alloc)
                continue
            payable = min(alloc.remaining_amount, remaining_to_pay)
            if payable > 0:
                new_alloc = alloc.record_payment(payable, payment_date, None)
                new_allocations.append(new_alloc)
                remaining_to_pay -= payable
            else:
                new_allocations.append(alloc)

        if remaining_to_pay > 0:
            raise DividendError(f"Could not allocate full payment amount {amount}")

        total_unpaid = sum(a.remaining_amount for a in new_allocations)
        new_status = DividendStatus.PAID if total_unpaid == 0 else DividendStatus.PARTIALLY_PAID
        now = datetime.now(UTC)

        new_entity = self._copy()
        new_entity.allocations = new_allocations
        new_entity.status = new_status
        new_entity.paid_by = paid_by
        if new_status == DividendStatus.PAID:
            new_entity.paid_at = now
        new_entity.updated_at = now
        new_entity.updated_by = paid_by
        new_entity.version = self.version + 1
        new_entity._record_audit("RECORD_PAYMENT", paid_by, {"amount": str(amount)})
        return new_entity

    def cancel(self, cancelled_by: str, reason: str) -> DividendDeclarationEntity:
        if not self.can_cancel:
            raise InvalidStatusTransitionError(
                f"Cannot cancel dividend in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = DividendStatus.CANCELLED
        new_entity.cancelled_by = cancelled_by
        new_entity.cancelled_at = now
        new_entity.cancel_reason = reason
        new_entity.updated_at = now
        new_entity.updated_by = cancelled_by
        new_entity.version = self.version + 1
        new_entity._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_entity

    def update_description(
        self, new_description: str, updated_by: str
    ) -> DividendDeclarationEntity:
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit dividend in status {self.status.value}"
            )
        new_entity = self._copy()
        new_entity.description = new_description
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = updated_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE_DESCRIPTION", updated_by, {})
        return new_entity

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> DividendDeclarationEntity:
        return DividendDeclarationEntity(
            dividend_id=self.dividend_id,
            legal_entity_id=self.legal_entity_id,
            dividend_number=self.dividend_number,
            dividend_type=self.dividend_type,
            declaration_date=self.declaration_date,
            record_date=self.record_date,
            payment_date=self.payment_date,
            total_amount=self.total_amount,
            currency=self.currency,
            status=self.status,
            description=self.description,
            resolution_reference=self.resolution_reference,
            allocations=[a for a in self.allocations],
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            paid_by=self.paid_by,
            paid_at=self.paid_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
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


class DividendDeclarationRepository:
    _storage: ClassVar[dict[UUID, dict[UUID, DividendDeclarationEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, DividendDeclarationEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    async def get_by_id(
        cls, dividend_id: UUID, legal_entity_id: UUID
    ) -> DividendDeclarationEntity | None:
        storage = cls._get_storage(legal_entity_id)
        return storage.get(dividend_id)

    @classmethod
    async def get_by_number(
        cls, dividend_number: str, legal_entity_id: UUID
    ) -> DividendDeclarationEntity | None:
        storage = cls._get_storage(legal_entity_id)
        for d in storage.values():
            if d.dividend_number == dividend_number:
                return d
        return None

    @classmethod
    async def get_by_status(
        cls, status: DividendStatus, legal_entity_id: UUID, limit: int = 100
    ) -> list[DividendDeclarationEntity]:
        storage = cls._get_storage(legal_entity_id)
        return [d for d in storage.values() if d.status == status][:limit]

    @classmethod
    async def get_by_date_range(
        cls, legal_entity_id: UUID, start_date: datetime, end_date: datetime, limit: int = 100
    ) -> list[DividendDeclarationEntity]:
        storage = cls._get_storage(legal_entity_id)
        result = [d for d in storage.values() if start_date <= d.declaration_date <= end_date]
        return result[:limit]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[DividendDeclarationEntity]:
        storage = cls._get_storage(legal_entity_id)
        return list(storage.values())

    @classmethod
    async def save(cls, dividend: DividendDeclarationEntity, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage[dividend.dividend_id] = dividend

    @classmethod
    async def update(cls, dividend: DividendDeclarationEntity, legal_entity_id: UUID) -> None:
        await cls.save(dividend, legal_entity_id)

    @classmethod
    async def delete(cls, dividend_id: UUID, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage.pop(dividend_id, None)

    @classmethod
    async def exists(cls, dividend_id: UUID, legal_entity_id: UUID) -> bool:
        storage = cls._get_storage(legal_entity_id)
        return dividend_id in storage

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        storage = cls._get_storage(legal_entity_id)
        return len(storage)

    @classmethod
    async def list(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[DividendDeclarationEntity]:
        dividends = await cls.get_all(legal_entity_id)
        return dividends[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[DividendDeclarationEntity], int]:
        dividends = await cls.get_all(legal_entity_id)
        total = len(dividends)
        start = (page - 1) * per_page
        end = start + per_page
        return dividends[start:end], total

    @classmethod
    async def search(
        cls, legal_entity_id: UUID, query: str, fields: list[str] | None = None
    ) -> list[DividendDeclarationEntity]:
        if fields is None:
            fields = ["dividend_number", "description"]
        dividends = await cls.get_all(legal_entity_id)
        query_lower = query.lower()
        results = []
        for d in dividends:
            for field in fields:
                value = getattr(d, field, "")
                if value and query_lower in str(value).lower():
                    results.append(d)
                    break
        return results

    @classmethod
    async def lock(
        cls, dividend_id: UUID, legal_entity_id: UUID, locked_by: str, reason: str
    ) -> DividendDeclarationEntity:
        d = await cls.get_by_id(dividend_id, legal_entity_id)
        if not d:
            raise ValueError(f"Dividend {dividend_id} not found")
        locked = d.lock(locked_by, reason)
        await cls.save(locked, legal_entity_id)
        return locked

    @classmethod
    async def unlock(
        cls, dividend_id: UUID, legal_entity_id: UUID, unlocked_by: str
    ) -> DividendDeclarationEntity:
        d = await cls.get_by_id(dividend_id, legal_entity_id)
        if not d:
            raise ValueError(f"Dividend {dividend_id} not found")
        unlocked = d.unlock(unlocked_by)
        await cls.save(unlocked, legal_entity_id)
        return unlocked

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        if legal_entity_id in cls._storage:
            cls._storage[legal_entity_id] = {}


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_dividend_per_share(total_amount: Decimal, total_shares: Decimal) -> Decimal:
    if total_shares <= 0:
        raise DividendError("Total shares must be positive")
    return (total_amount / total_shares).quantize(Decimal("0.0001"))


def allocate_dividend_by_shares(
    shareholders: list[tuple[UUID, str, Decimal]], total_amount: Decimal, total_shares: Decimal
) -> list[DividendShareholderAllocation]:
    dividend_per_share = calculate_dividend_per_share(total_amount, total_shares)
    allocations = []
    for sh_id, sh_name, shares in shareholders:
        amount = (dividend_per_share * shares).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        share_pct = (shares / total_shares * Decimal("100")).quantize(Decimal("0.0001"))
        allocations.append(
            DividendShareholderAllocation(
                shareholder_id=sh_id,
                shareholder_name=sh_name,
                shares_owned=shares,
                share_percentage=share_pct,
                dividend_amount=amount,
            )
        )
    return allocations


__all__ = [
    "AllocationMismatchError",
    "DividendDeclarationEntity",
    "DividendDeclarationRepository",
    "DividendError",
    "DividendShareholderAllocation",
    "DividendStatus",
    "DividendType",
    "InvalidDividendAmountError",
    "InvalidDividendDatesError",
    "InvalidStatusTransitionError",
    "allocate_dividend_by_shares",
    "calculate_dividend_per_share",
]
