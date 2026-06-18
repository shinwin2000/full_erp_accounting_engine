#!/usr/bin/env python3
"""
Module: capital_contribution_entity.py
Layer: Domain / Equity & Retained Earnings
Responsibility: Entity untuk capital contribution (setoran modal) dengan semua method entity dasar.
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


class ContributionType(Enum):
    INITIAL = "initial"
    ADDITIONAL = "additional"
    CONVERSION = "conversion"
    ASSET = "asset"
    REVALUATION = "revaluation"
    BONUS_SHARE = "bonus_share"

    def display_name(self) -> str:
        names = {
            ContributionType.INITIAL: "Setoran Awal",
            ContributionType.ADDITIONAL: "Setoran Tambahan",
            ContributionType.CONVERSION: "Konversi Hutang",
            ContributionType.ASSET: "Setoran Aset",
            ContributionType.REVALUATION: "Revaluasi",
            ContributionType.BONUS_SHARE: "Bonus Saham",
        }
        return names.get(self, self.value)


class ContributionStatus(Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    POSTED = "posted"
    CANCELLED = "cancelled"

    def can_edit(self) -> bool:
        return self == ContributionStatus.DRAFT

    def can_approve(self) -> bool:
        return self == ContributionStatus.DRAFT

    def can_post(self) -> bool:
        return self == ContributionStatus.APPROVED

    def can_cancel(self) -> bool:
        return self in (ContributionStatus.DRAFT, ContributionStatus.APPROVED)

    def display_name(self) -> str:
        names = {
            ContributionStatus.DRAFT: "Draft",
            ContributionStatus.APPROVED: "Disetujui",
            ContributionStatus.POSTED: "Diposting",
            ContributionStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)


# ============================================================================
# Custom Exceptions
# ============================================================================


class CapitalContributionError(ValueError):
    pass


class InvalidContributionAmountError(CapitalContributionError):
    pass


class InvalidSharePercentageError(CapitalContributionError):
    pass


class InvalidStatusTransitionError(CapitalContributionError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_contribution_number(number: str) -> str:
    if not number or not isinstance(number, str):
        raise CapitalContributionError("Contribution number must be a non-empty string")
    cleaned = number.strip()
    if len(cleaned) < 3:
        raise CapitalContributionError("Contribution number must be at least 3 characters")
    if len(cleaned) > 30:
        raise CapitalContributionError("Contribution number must not exceed 30 characters")
    if not re.match(r"^[A-Za-z0-9\-_/]+$", cleaned):
        raise CapitalContributionError(
            "Contribution number can only contain letters, numbers, hyphens, underscores, and slashes"
        )
    return cleaned


def _validate_amount(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount))
        except Exception:
            raise InvalidContributionAmountError(f"Invalid amount type: {type(amount)}")
    if amount <= 0:
        raise InvalidContributionAmountError(f"Contribution amount must be positive: {amount}")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_share_percentage(percentage: Decimal | None) -> Decimal | None:
    if percentage is None:
        return None
    if not isinstance(percentage, Decimal):
        try:
            percentage = Decimal(str(percentage))
        except Exception:
            raise InvalidSharePercentageError(f"Invalid percentage type: {type(percentage)}")
    if percentage < 0 or percentage > 100:
        raise InvalidSharePercentageError(
            f"Share percentage must be between 0 and 100: {percentage}"
        )
    return percentage.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def _validate_currency(currency: str) -> str:
    if not currency or not isinstance(currency, str):
        raise CapitalContributionError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise CapitalContributionError(
            f"Currency code must be exactly 3 characters, got '{cleaned}'"
        )
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise CapitalContributionError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


# ============================================================================
# Entity: CapitalContributionEntity
# ============================================================================


@dataclass
class CapitalContributionEntity:
    contribution_id: UUID
    legal_entity_id: UUID
    contribution_number: str
    contribution_type: ContributionType
    shareholder_id: UUID
    shareholder_name: str
    amount: Decimal
    currency: str
    contribution_date: datetime
    status: ContributionStatus
    description: str = ""
    share_percentage: Decimal | None = None
    asset_description: str = ""
    asset_valuation_date: datetime | None = None
    approval_reference: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    posted_by: str | None = None
    posted_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        # Validate contribution_number
        normalized_number = _validate_contribution_number(self.contribution_number)
        if normalized_number != self.contribution_number:
            object.__setattr__(self, "contribution_number", normalized_number)

        # Validate contribution_type
        if not isinstance(self.contribution_type, ContributionType):
            raise CapitalContributionError(f"Invalid contribution_type: {self.contribution_type}")

        # Validate shareholder_name
        if not self.shareholder_name or not isinstance(self.shareholder_name, str):
            raise CapitalContributionError("Shareholder name must be a non-empty string")
        name_clean = self.shareholder_name.strip()
        if len(name_clean) < 2:
            raise CapitalContributionError("Shareholder name must be at least 2 characters")
        if len(name_clean) > 200:
            raise CapitalContributionError("Shareholder name must not exceed 200 characters")
        object.__setattr__(self, "shareholder_name", name_clean)

        # Validate amount
        normalized_amount = _validate_amount(self.amount)
        if normalized_amount != self.amount:
            object.__setattr__(self, "amount", normalized_amount)

        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Validate contribution_date UTC
        if self.contribution_date.tzinfo is None:
            object.__setattr__(
                self, "contribution_date", self.contribution_date.replace(tzinfo=UTC)
            )

        # Validate status
        if not isinstance(self.status, ContributionStatus):
            raise CapitalContributionError(f"Invalid status: {self.status}")

        # Validate share_percentage
        if self.share_percentage is not None:
            normalized_pct = _validate_share_percentage(self.share_percentage)
            if normalized_pct != self.share_percentage:
                object.__setattr__(self, "share_percentage", normalized_pct)

        # Validate asset_valuation_date
        if self.asset_valuation_date and self.asset_valuation_date.tzinfo is None:
            object.__setattr__(
                self, "asset_valuation_date", self.asset_valuation_date.replace(tzinfo=UTC)
            )

        # Validate approval dates
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.posted_at and self.posted_at.tzinfo is None:
            object.__setattr__(self, "posted_at", self.posted_at.replace(tzinfo=UTC))
        if self.cancelled_at and self.cancelled_at.tzinfo is None:
            object.__setattr__(self, "cancelled_at", self.cancelled_at.replace(tzinfo=UTC))

        # Validate status consistency
        if self.status == ContributionStatus.APPROVED and not self.approved_by:
            raise CapitalContributionError("Approved contribution must have approved_by")
        if self.status == ContributionStatus.POSTED and not self.posted_by:
            raise CapitalContributionError("Posted contribution must have posted_by")
        if self.status == ContributionStatus.CANCELLED and not self.cancelled_by:
            raise CapitalContributionError("Cancelled contribution must have cancelled_by")

        # Validate timestamps UTC
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise CapitalContributionError("Version must be >= 1")

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "contribution_id": str(self.contribution_id),
            "number": self.contribution_number,
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
            "contribution_id": str(self.contribution_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> CapitalContributionEntity:
        self._record_audit(
            "CREATE", created_by, {"number": self.contribution_number, "amount": str(self.amount)}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> CapitalContributionEntity:
        if not self.status.can_edit():
            raise InvalidStatusTransitionError(
                f"Cannot update contribution in status {self.status.value}"
            )
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("contribution_id", "created_at", "created_by", "version"):
                data[key] = value
        new_entity = self.from_dict(data)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = updated_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entity

    def delete(self, deleted_by: str, reason: str | None = None) -> CapitalContributionEntity:
        if self.status not in (ContributionStatus.DRAFT, ContributionStatus.CANCELLED):
            raise InvalidStatusTransitionError(
                f"Cannot delete contribution in status {self.status.value}"
            )
        new_entity = self.cancel(deleted_by, reason or "Deleted by user")
        new_entity._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entity

    def restore(self, restored_by: str) -> CapitalContributionEntity:
        if self.status != ContributionStatus.CANCELLED:
            raise InvalidStatusTransitionError(
                f"Cannot restore contribution in status {self.status.value}"
            )
        # Restore to DRAFT (original state)
        new_entity = self._copy()
        new_entity.status = ContributionStatus.DRAFT
        new_entity.cancelled_by = None
        new_entity.cancelled_at = None
        new_entity.cancel_reason = ""
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = restored_by
        new_entity.version = self.version + 1
        new_entity._record_audit("RESTORE", restored_by, {})
        return new_entity

    def activate(self, activated_by: str) -> CapitalContributionEntity:
        if self.status != ContributionStatus.DRAFT:
            raise InvalidStatusTransitionError(
                f"Cannot activate contribution in status {self.status.value}"
            )
        return self.approve(activated_by)

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> CapitalContributionEntity:
        if self.status != ContributionStatus.DRAFT:
            raise InvalidStatusTransitionError(
                f"Cannot deactivate contribution in status {self.status.value}"
            )
        return self.cancel(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: str, reason: str) -> CapitalContributionEntity:
        # Locking is not a standard status; we use metadata instead
        new_entity = self._copy()
        if new_entity.metadata is None:
            object.__setattr__(new_entity, "metadata", {})
        new_entity.metadata["locked_by"] = locked_by
        new_entity.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_entity.metadata["lock_reason"] = reason
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = locked_by
        new_entity.version = self.version + 1
        new_entity._record_audit("LOCK", locked_by, {"reason": reason})
        return new_entity

    def unlock(self, unlocked_by: str) -> CapitalContributionEntity:
        new_entity = self._copy()
        if new_entity.metadata:
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
        except CapitalContributionError as e:
            errors.append(str(e))
        if self.status == ContributionStatus.POSTED and self.posted_at is None:
            errors.append("Posted status requires posted_at")
        if self.status == ContributionStatus.APPROVED and self.approved_at is None:
            errors.append("Approved status requires approved_at")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "contribution_id": str(self.contribution_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contribution_id": str(self.contribution_id),
            "legal_entity_id": str(self.legal_entity_id),
            "contribution_number": self.contribution_number,
            "contribution_type": self.contribution_type.value,
            "shareholder_id": str(self.shareholder_id),
            "shareholder_name": self.shareholder_name,
            "amount": str(self.amount),
            "currency": self.currency,
            "contribution_date": self.contribution_date.isoformat(),
            "status": self.status.value,
            "description": self.description,
            "share_percentage": str(self.share_percentage) if self.share_percentage else None,
            "asset_description": self.asset_description,
            "asset_valuation_date": self.asset_valuation_date.isoformat()
            if self.asset_valuation_date
            else None,
            "approval_reference": self.approval_reference,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "posted_by": self.posted_by,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapitalContributionEntity:
        contribution_type = ContributionType(data["contribution_type"])
        status = ContributionStatus(data["status"])
        contribution_date = datetime.fromisoformat(data["contribution_date"])
        asset_valuation_date = (
            datetime.fromisoformat(data["asset_valuation_date"])
            if data.get("asset_valuation_date")
            else None
        )
        approved_at = (
            datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None
        )
        posted_at = datetime.fromisoformat(data["posted_at"]) if data.get("posted_at") else None
        cancelled_at = (
            datetime.fromisoformat(data["cancelled_at"]) if data.get("cancelled_at") else None
        )
        return cls(
            contribution_id=UUID(data["contribution_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            contribution_number=data["contribution_number"],
            contribution_type=contribution_type,
            shareholder_id=UUID(data["shareholder_id"]),
            shareholder_name=data["shareholder_name"],
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            contribution_date=contribution_date,
            status=status,
            description=data.get("description", ""),
            share_percentage=Decimal(data["share_percentage"])
            if data.get("share_percentage")
            else None,
            asset_description=data.get("asset_description", ""),
            asset_valuation_date=asset_valuation_date,
            approval_reference=data.get("approval_reference"),
            approved_by=data.get("approved_by"),
            approved_at=approved_at,
            posted_by=data.get("posted_by"),
            posted_at=posted_at,
            cancelled_by=data.get("cancelled_by"),
            cancelled_at=cancelled_at,
            cancel_reason=data.get("cancel_reason", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self, new_number: str | None = None) -> CapitalContributionEntity:
        new_id = uuid4()
        new_number_str = new_number or f"{self.contribution_number}_COPY"
        now = datetime.now(UTC)
        cloned = CapitalContributionEntity(
            contribution_id=new_id,
            legal_entity_id=self.legal_entity_id,
            contribution_number=new_number_str,
            contribution_type=self.contribution_type,
            shareholder_id=self.shareholder_id,
            shareholder_name=self.shareholder_name,
            amount=self.amount,
            currency=self.currency,
            contribution_date=self.contribution_date,
            status=ContributionStatus.DRAFT,
            description=f"Cloned from {self.contribution_number}",
            share_percentage=self.share_percentage,
            asset_description=self.asset_description,
            asset_valuation_date=self.asset_valuation_date,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            updated_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.contribution_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "contribution_id": str(self.contribution_id),
            "number": self.contribution_number,
            "amount": str(self.amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CapitalContributionEntity:
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = touched_by
        new_entity.version = self.version + 1
        new_entity._record_audit("TOUCH", touched_by, {})
        return new_entity

    # ==================== BUSINESS LOGIC ====================

    @property
    def is_draft(self) -> bool:
        return self.status == ContributionStatus.DRAFT

    @property
    def is_approved(self) -> bool:
        return self.status == ContributionStatus.APPROVED

    @property
    def is_posted(self) -> bool:
        return self.status == ContributionStatus.POSTED

    @property
    def is_cancelled(self) -> bool:
        return self.status == ContributionStatus.CANCELLED

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

    def approve(
        self, approved_by: str, approval_reference: str | None = None
    ) -> CapitalContributionEntity:
        if not self.can_approve:
            raise InvalidStatusTransitionError(
                f"Cannot approve contribution in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = ContributionStatus.APPROVED
        new_entity.approved_by = approved_by
        new_entity.approved_at = now
        if approval_reference:
            new_entity.approval_reference = approval_reference
        new_entity.updated_at = now
        new_entity.updated_by = approved_by
        new_entity.version = self.version + 1
        new_entity._record_audit("APPROVE", approved_by, {"reference": approval_reference})
        return new_entity

    def post(self, posted_by: str) -> CapitalContributionEntity:
        if not self.can_post:
            raise InvalidStatusTransitionError(
                f"Cannot post contribution in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = ContributionStatus.POSTED
        new_entity.posted_by = posted_by
        new_entity.posted_at = now
        new_entity.updated_at = now
        new_entity.updated_by = posted_by
        new_entity.version = self.version + 1
        new_entity._record_audit("POST", posted_by, {})
        return new_entity

    def cancel(self, cancelled_by: str, reason: str) -> CapitalContributionEntity:
        if not self.can_cancel:
            raise InvalidStatusTransitionError(
                f"Cannot cancel contribution in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_entity = self._copy()
        new_entity.status = ContributionStatus.CANCELLED
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
    ) -> CapitalContributionEntity:
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit contribution in status {self.status.value}"
            )
        new_entity = self._copy()
        new_entity.description = new_description
        new_entity.updated_at = datetime.now(UTC)
        new_entity.updated_by = updated_by
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE_DESCRIPTION", updated_by, {})
        return new_entity

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> CapitalContributionEntity:
        return CapitalContributionEntity(
            contribution_id=self.contribution_id,
            legal_entity_id=self.legal_entity_id,
            contribution_number=self.contribution_number,
            contribution_type=self.contribution_type,
            shareholder_id=self.shareholder_id,
            shareholder_name=self.shareholder_name,
            amount=self.amount,
            currency=self.currency,
            contribution_date=self.contribution_date,
            status=self.status,
            description=self.description,
            share_percentage=self.share_percentage,
            asset_description=self.asset_description,
            asset_valuation_date=self.asset_valuation_date,
            approval_reference=self.approval_reference,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class CapitalContributionRepository:
    _storage: ClassVar[dict[UUID, dict[UUID, CapitalContributionEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, CapitalContributionEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    async def get_by_id(
        cls, contribution_id: UUID, legal_entity_id: UUID
    ) -> CapitalContributionEntity | None:
        storage = cls._get_storage(legal_entity_id)
        return storage.get(contribution_id)

    @classmethod
    async def get_by_number(
        cls, contribution_number: str, legal_entity_id: UUID
    ) -> CapitalContributionEntity | None:
        storage = cls._get_storage(legal_entity_id)
        for c in storage.values():
            if c.contribution_number == contribution_number:
                return c
        return None

    @classmethod
    async def get_by_shareholder(
        cls, shareholder_id: UUID, legal_entity_id: UUID, limit: int = 100
    ) -> list[CapitalContributionEntity]:
        storage = cls._get_storage(legal_entity_id)
        return [c for c in storage.values() if c.shareholder_id == shareholder_id][:limit]

    @classmethod
    async def get_by_status(
        cls, status: ContributionStatus, legal_entity_id: UUID, limit: int = 100
    ) -> list[CapitalContributionEntity]:
        storage = cls._get_storage(legal_entity_id)
        return [c for c in storage.values() if c.status == status][:limit]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[CapitalContributionEntity]:
        storage = cls._get_storage(legal_entity_id)
        return list(storage.values())

    @classmethod
    async def save(cls, contribution: CapitalContributionEntity, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage[contribution.contribution_id] = contribution

    @classmethod
    async def update(cls, contribution: CapitalContributionEntity, legal_entity_id: UUID) -> None:
        await cls.save(contribution, legal_entity_id)

    @classmethod
    async def delete(cls, contribution_id: UUID, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage.pop(contribution_id, None)

    @classmethod
    async def exists(cls, contribution_id: UUID, legal_entity_id: UUID) -> bool:
        storage = cls._get_storage(legal_entity_id)
        return contribution_id in storage

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        storage = cls._get_storage(legal_entity_id)
        return len(storage)

    @classmethod
    async def list(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CapitalContributionEntity]:
        contributions = await cls.get_all(legal_entity_id)
        return contributions[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[CapitalContributionEntity], int]:
        contributions = await cls.get_all(legal_entity_id)
        total = len(contributions)
        start = (page - 1) * per_page
        end = start + per_page
        return contributions[start:end], total

    @classmethod
    async def search(
        cls, legal_entity_id: UUID, query: str, fields: list[str] | None = None
    ) -> list[CapitalContributionEntity]:
        if fields is None:
            fields = ["contribution_number", "shareholder_name", "description"]
        contributions = await cls.get_all(legal_entity_id)
        query_lower = query.lower()
        results = []
        for c in contributions:
            for field in fields:
                value = getattr(c, field, "")
                if value and query_lower in str(value).lower():
                    results.append(c)
                    break
        return results

    @classmethod
    async def lock(
        cls, contribution_id: UUID, legal_entity_id: UUID, locked_by: str, reason: str
    ) -> CapitalContributionEntity:
        c = await cls.get_by_id(contribution_id, legal_entity_id)
        if not c:
            raise ValueError(f"Contribution {contribution_id} not found")
        locked = c.lock(locked_by, reason)
        await cls.save(locked, legal_entity_id)
        return locked

    @classmethod
    async def unlock(
        cls, contribution_id: UUID, legal_entity_id: UUID, unlocked_by: str
    ) -> CapitalContributionEntity:
        c = await cls.get_by_id(contribution_id, legal_entity_id)
        if not c:
            raise ValueError(f"Contribution {contribution_id} not found")
        unlocked = c.unlock(unlocked_by)
        await cls.save(unlocked, legal_entity_id)
        return unlocked

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        if legal_entity_id in cls._storage:
            cls._storage[legal_entity_id] = {}


__all__ = [
    "CapitalContributionEntity",
    "CapitalContributionError",
    "CapitalContributionRepository",
    "ContributionStatus",
    "ContributionType",
    "InvalidContributionAmountError",
    "InvalidSharePercentageError",
    "InvalidStatusTransitionError",
]
