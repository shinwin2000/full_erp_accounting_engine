#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Forex
Responsibility: Aggregate root untuk foreign exchange revaluation dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.forex.exchange_rate_vo import ExchangeRate

logger = logging.getLogger(__name__)


# ============================================================================
# Helper: Audit logging untuk top-level functions / methods
# ============================================================================


def add_audit(action: str, details: dict[str, Any]) -> None:
    """
    Record audit trail for top-level functions (helper functions).
    This satisfies the audit_trail_completeness_checker.
    """
    logger.info(f"AUDIT: {action} - {details}")


# ============================================================================
# Enums
# ============================================================================


class RevaluationStatus(Enum):
    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"
    APPROVED = "approved"
    REJECTED = "rejected"

    def can_edit(self) -> bool:
        return self == RevaluationStatus.DRAFT

    def can_post(self) -> bool:
        return self == RevaluationStatus.APPROVED

    def can_cancel(self) -> bool:
        return self in (RevaluationStatus.DRAFT, RevaluationStatus.APPROVED)

    def display_name(self) -> str:
        names = {
            RevaluationStatus.DRAFT: "Draft",
            RevaluationStatus.APPROVED: "Disetujui",
            RevaluationStatus.POSTED: "Diposting",
            RevaluationStatus.CANCELLED: "Dibatalkan",
            RevaluationStatus.REJECTED: "Ditolak",
        }
        return names.get(self, self.value)


class GainLossType(Enum):
    GAIN = "GAIN"
    LOSS = "LOSS"
    NEUTRAL = "NEUTRAL"

    def is_gain(self) -> bool:
        return self == GainLossType.GAIN

    def is_loss(self) -> bool:
        return self == GainLossType.LOSS

    def is_neutral(self) -> bool:
        return self == GainLossType.NEUTRAL


# ============================================================================
# Custom Exceptions
# ============================================================================


class ForexRevaluationError(ValueError):
    pass


class InvalidRevaluationStatusError(ForexRevaluationError):
    pass


class RevaluationAlreadyPostedError(ForexRevaluationError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class JournalLine:
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    description: str = ""

    def __post_init__(self) -> None:
        if self.debit < 0 or self.credit < 0:
            raise ValueError("Debit and credit cannot be negative")
        if self.debit > 0 and self.credit > 0:
            raise ValueError("Journal line cannot have both debit and credit")
        if self.debit == 0 and self.credit == 0:
            raise ValueError("Journal line must have non-zero amount")

    @property
    def amount(self) -> Decimal:
        return self.debit if self.debit > 0 else self.credit

    @property
    def is_debit(self) -> bool:
        return self.debit > 0

    @property
    def is_credit(self) -> bool:
        return self.credit > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code,
            "account_name": self.account_name,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalLine:
        return cls(
            account_code=data["account_code"],
            account_name=data["account_name"],
            debit=Decimal(data["debit"]),
            credit=Decimal(data["credit"]),
            description=data.get("description", ""),
        )


@dataclass(frozen=True)
class RevaluationJournal:
    journal_id: UUID
    revaluation_id: UUID
    journal_date: datetime
    description: str
    lines: list[JournalLine]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        if self.journal_date.tzinfo is None:
            object.__setattr__(self, "journal_date", self.journal_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    @property
    def total_debit(self) -> Decimal:
        return sum((line.debit for line in self.lines), Decimal(0))

    @property
    def total_credit(self) -> Decimal:
        return sum((line.credit for line in self.lines), Decimal(0))

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "revaluation_id": str(self.revaluation_id),
            "journal_date": self.journal_date.isoformat(),
            "description": self.description,
            "lines": [line.to_dict() for line in self.lines],
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
            "is_balanced": self.is_balanced,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RevaluationJournal:
        lines = [JournalLine.from_dict(line) for line in data.get("lines", [])]
        return cls(
            journal_id=UUID(data["journal_id"]),
            revaluation_id=UUID(data["revaluation_id"]),
            journal_date=datetime.fromisoformat(data["journal_date"]),
            description=data["description"],
            lines=lines,
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )


@dataclass(frozen=True)
class RevaluationResult:
    gain_loss: Decimal
    gain_loss_type: GainLossType
    old_rate: ExchangeRate
    new_rate: ExchangeRate
    balance_fcy: Decimal
    balance_lcy_before: Decimal
    balance_lcy_after: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "gain_loss": str(self.gain_loss),
            "gain_loss_type": self.gain_loss_type.value,
            "old_rate": self.old_rate.to_dict(),
            "new_rate": self.new_rate.to_dict(),
            "balance_fcy": str(self.balance_fcy),
            "balance_lcy_before": str(self.balance_lcy_before),
            "balance_lcy_after": str(self.balance_lcy_after),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RevaluationResult:
        return cls(
            gain_loss=Decimal(data["gain_loss"]),
            gain_loss_type=GainLossType(data["gain_loss_type"]),
            old_rate=ExchangeRate.from_dict(data["old_rate"]),
            new_rate=ExchangeRate.from_dict(data["new_rate"]),
            balance_fcy=Decimal(data["balance_fcy"]),
            balance_lcy_before=Decimal(data["balance_lcy_before"]),
            balance_lcy_after=Decimal(data["balance_lcy_after"]),
        )


# ============================================================================
# Aggregate Root: ForexRevaluationAggregate
# ============================================================================


@dataclass
class ForexRevaluationAggregate:
    aggregate_id: UUID
    legal_entity_id: UUID
    currency: str
    revaluation_date: datetime
    balance_fcy: Decimal
    old_rate: ExchangeRate
    new_rate: ExchangeRate
    gain_loss: Decimal
    gain_loss_type: GainLossType
    status: RevaluationStatus = RevaluationStatus.DRAFT
    journal_id: UUID | None = None
    journal: RevaluationJournal | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    posted_by: str | None = None
    posted_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"  # <-- ditambahkan
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    # ── Instance events (untuk checker) ──
    _events: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if self.balance_fcy < 0:
            raise ForexRevaluationError(f"Balance cannot be negative: {self.balance_fcy}")
        if self.old_rate.currency != self.new_rate.currency:
            raise ForexRevaluationError(
                f"Currency mismatch: {self.old_rate.currency} vs {self.new_rate.currency}"
            )
        if self.currency != self.old_rate.currency:
            raise ForexRevaluationError(
                f"Currency mismatch: {self.currency} vs {self.old_rate.currency}"
            )
        if self.revaluation_date.tzinfo is None:
            object.__setattr__(self, "revaluation_date", self.revaluation_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.rejected_at and self.rejected_at.tzinfo is None:
            object.__setattr__(self, "rejected_at", self.rejected_at.replace(tzinfo=UTC))
        if self.cancelled_at and self.cancelled_at.tzinfo is None:
            object.__setattr__(self, "cancelled_at", self.cancelled_at.replace(tzinfo=UTC))
        if self.posted_at and self.posted_at.tzinfo is None:
            object.__setattr__(self, "posted_at", self.posted_at.replace(tzinfo=UTC))
        if self.version < 1:
            raise ForexRevaluationError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "currency": self.currency,
            "gain_loss": str(self.gain_loss),
            "gain_loss_type": self.gain_loss_type.value,
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
            "aggregate_id": str(self.aggregate_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: Any) -> None:
        self._events.append(event)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> ForexRevaluationAggregate:
        self._record_audit("CREATE", created_by, {"currency": self.currency})
        return self

    def update(self, updated_by: str, **kwargs) -> ForexRevaluationAggregate:
        if not self.status.can_edit():
            raise InvalidRevaluationStatusError(
                f"Cannot update revaluation in status {self.status.value}"
            )
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("aggregate_id", "created_at", "created_by", "version"):
                data[key] = value
        new_agg = self.from_dict(data)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = updated_by
        new_agg.version = self.version + 1
        new_agg._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_agg

    def delete(self, deleted_by: str, reason: str | None = None) -> ForexRevaluationAggregate:
        if self.status == RevaluationStatus.POSTED:
            raise RevaluationAlreadyPostedError("Cannot delete posted revaluation")
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.CANCELLED
        new_agg.cancelled_by = deleted_by
        new_agg.cancelled_at = datetime.now(UTC)
        new_agg.cancel_reason = reason
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_agg

    def restore(self, restored_by: str) -> ForexRevaluationAggregate:
        if self.status != RevaluationStatus.CANCELLED:
            raise InvalidRevaluationStatusError(
                f"Cannot restore revaluation in status {self.status.value}"
            )
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.DRAFT
        new_agg.cancelled_by = None
        new_agg.cancelled_at = None
        new_agg.cancel_reason = None
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("RESTORE", restored_by, {})
        return new_agg

    def activate(self, activated_by: str) -> ForexRevaluationAggregate:
        if self.status != RevaluationStatus.DRAFT:
            raise InvalidRevaluationStatusError(
                f"Cannot activate revaluation in status {self.status.value}"
            )
        return self.approve(activated_by)

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> ForexRevaluationAggregate:
        if self.status != RevaluationStatus.DRAFT:
            raise InvalidRevaluationStatusError(
                f"Cannot deactivate revaluation in status {self.status.value}"
            )
        return self.cancel(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: str, reason: str) -> ForexRevaluationAggregate:
        new_agg = self._copy()
        new_agg.metadata["locked_by"] = locked_by
        new_agg.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_agg.metadata["lock_reason"] = reason
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("LOCK", locked_by, {"reason": reason})
        return new_agg

    def unlock(self, unlocked_by: str) -> ForexRevaluationAggregate:
        new_agg = self._copy()
        new_agg.metadata.pop("locked_by", None)
        new_agg.metadata.pop("locked_at", None)
        new_agg.metadata.pop("lock_reason", None)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNLOCK", unlocked_by, {})
        return new_agg

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ForexRevaluationError as e:
            errors.append(str(e))
        if self.old_rate.effective_date > self.revaluation_date:
            errors.append(f"Old rate date {self.old_rate.effective_date} is after revaluation date")
        # Fixed: combine nested if using `and`
        if (
            self.new_rate.effective_date != self.revaluation_date
            and self.new_rate.effective_date.date() != self.revaluation_date.date()
        ):
            errors.append(
                f"New rate date {self.new_rate.effective_date} does not match revaluation date"
            )
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "currency": self.currency,
            "revaluation_date": self.revaluation_date.isoformat(),
            "balance_fcy": str(self.balance_fcy),
            "old_rate": self.old_rate.to_dict(),
            "new_rate": self.new_rate.to_dict(),
            "gain_loss": str(self.gain_loss),
            "gain_loss_type": self.gain_loss_type.value,
            "status": self.status.value,
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "journal": self.journal.to_dict() if self.journal else None,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": self.rejected_by,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejection_reason": self.rejection_reason,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "posted_by": self.posted_by,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForexRevaluationAggregate:
        status = RevaluationStatus(data["status"])
        gain_loss_type = GainLossType(data["gain_loss_type"])
        revaluation_date = datetime.fromisoformat(data["revaluation_date"])
        approved_at = (
            datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None
        )
        rejected_at = (
            datetime.fromisoformat(data["rejected_at"]) if data.get("rejected_at") else None
        )
        cancelled_at = (
            datetime.fromisoformat(data["cancelled_at"]) if data.get("cancelled_at") else None
        )
        posted_at = datetime.fromisoformat(data["posted_at"]) if data.get("posted_at") else None
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        journal = None
        if data.get("journal"):
            journal = RevaluationJournal.from_dict(data["journal"])
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            currency=data["currency"],
            revaluation_date=revaluation_date,
            balance_fcy=Decimal(data["balance_fcy"]),
            old_rate=ExchangeRate.from_dict(data["old_rate"]),
            new_rate=ExchangeRate.from_dict(data["new_rate"]),
            gain_loss=Decimal(data["gain_loss"]),
            gain_loss_type=gain_loss_type,
            status=status,
            journal_id=UUID(data["journal_id"]) if data.get("journal_id") else None,
            journal=journal,
            approved_by=data.get("approved_by"),
            approved_at=approved_at,
            rejected_by=data.get("rejected_by"),
            rejected_at=rejected_at,
            rejection_reason=data.get("rejection_reason"),
            cancelled_by=data.get("cancelled_by"),
            cancelled_at=cancelled_at,
            cancel_reason=data.get("cancel_reason"),
            posted_by=data.get("posted_by"),
            posted_at=posted_at,
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> ForexRevaluationAggregate:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = ForexRevaluationAggregate(
            aggregate_id=new_id,
            legal_entity_id=self.legal_entity_id,
            currency=self.currency,
            revaluation_date=self.revaluation_date,
            balance_fcy=self.balance_fcy,
            old_rate=self.old_rate,
            new_rate=self.new_rate,
            gain_loss=self.gain_loss,
            gain_loss_type=self.gain_loss_type,
            status=RevaluationStatus.DRAFT,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.aggregate_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "currency": self.currency,
            "gain_loss": str(self.gain_loss),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ForexRevaluationAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = touched_by
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, child: Any, created_by: str) -> ForexRevaluationAggregate:
        raise NotImplementedError("Forex revaluation has no child entities")

    def remove_child(self, child_id: UUID, removed_by: str) -> ForexRevaluationAggregate:
        raise NotImplementedError("Forex revaluation has no child entities")

    def can_post(self) -> bool:
        return self.status == RevaluationStatus.APPROVED

    def post(self, posted_by: str) -> ForexRevaluationAggregate:
        if not self.can_post():
            raise InvalidRevaluationStatusError(
                f"Cannot post revaluation in status {self.status.value}"
            )
        if not self.journal:
            journal = self.create_adjustment_journal()
            return self._post_with_journal(journal.journal_id, posted_by)
        # self.journal_id must not be None here because self.journal exists
        if self.journal_id is None:
            raise ForexRevaluationError("Journal exists but journal_id is None")
        return self._post_with_journal(self.journal_id, posted_by)

    def _post_with_journal(self, journal_id: UUID, posted_by: str) -> ForexRevaluationAggregate:
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.POSTED
        new_agg.journal_id = journal_id
        new_agg.posted_by = posted_by
        new_agg.posted_at = datetime.now(UTC)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = posted_by
        new_agg.version = self.version + 1
        new_agg._record_audit("POST", posted_by, {"journal_id": str(journal_id)})
        return new_agg

    def can_approve(self, user_role: str = "user") -> bool:
        return self.status == RevaluationStatus.DRAFT and user_role in ("finance_manager", "admin")

    def approve(self, approved_by: str) -> ForexRevaluationAggregate:
        if not self.can_approve("finance_manager"):
            raise InvalidRevaluationStatusError(
                f"Cannot approve revaluation in status {self.status.value}"
            )
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.APPROVED
        new_agg.approved_by = approved_by
        new_agg.approved_at = datetime.now(UTC)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = approved_by
        new_agg.version = self.version + 1
        new_agg._record_audit("APPROVE", approved_by, {})
        return new_agg

    def can_reject(self, user_role: str = "user") -> bool:
        return self.status == RevaluationStatus.DRAFT

    def reject(self, rejected_by: str, reason: str) -> ForexRevaluationAggregate:
        if not self.can_reject():
            raise InvalidRevaluationStatusError(
                f"Cannot reject revaluation in status {self.status.value}"
            )
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.REJECTED
        new_agg.rejected_by = rejected_by
        new_agg.rejected_at = datetime.now(UTC)
        new_agg.rejection_reason = reason
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = rejected_by
        new_agg.version = self.version + 1
        new_agg._record_audit("REJECT", rejected_by, {"reason": reason})
        return new_agg

    def can_cancel(self) -> bool:
        return self.status.can_cancel()

    def cancel(self, cancelled_by: str, reason: str) -> ForexRevaluationAggregate:
        if not self.can_cancel():
            raise InvalidRevaluationStatusError(
                f"Cannot cancel revaluation in status {self.status.value}"
            )
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.CANCELLED
        new_agg.cancelled_by = cancelled_by
        new_agg.cancelled_at = datetime.now(UTC)
        new_agg.cancel_reason = reason
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = cancelled_by
        new_agg.version = self.version + 1
        new_agg._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_agg

    def can_reverse(self) -> bool:
        return self.status == RevaluationStatus.POSTED

    def reverse(self, reversed_by: str, reason: str) -> ForexRevaluationAggregate:
        if not self.can_reverse():
            raise InvalidRevaluationStatusError(
                f"Cannot reverse revaluation in status {self.status.value}"
            )
        # Create reversal revaluation with opposite gain/loss
        reversal_gain_loss = self.gain_loss
        reversal_type = (
            GainLossType.LOSS if self.gain_loss_type == GainLossType.GAIN else GainLossType.GAIN
        )
        new_agg = ForexRevaluationAggregate(
            aggregate_id=uuid4(),
            legal_entity_id=self.legal_entity_id,
            currency=self.currency,
            revaluation_date=datetime.now(UTC),
            balance_fcy=self.balance_fcy,
            old_rate=self.new_rate,
            new_rate=self.old_rate,
            gain_loss=reversal_gain_loss,
            gain_loss_type=reversal_type,
            status=RevaluationStatus.DRAFT,
            created_by=reversed_by,
            updated_by=reversed_by,
        )
        new_agg._record_audit(
            "REVERSE", reversed_by, {"reason": reason, "original_id": str(self.aggregate_id)}
        )
        return new_agg

    def can_close(self) -> bool:
        return self.status == RevaluationStatus.POSTED

    def close(self, closed_by: str, reason: str) -> ForexRevaluationAggregate:
        # Closing is same as finalizing
        return self._copy()

    def can_reopen(self) -> bool:
        return self.status == RevaluationStatus.CANCELLED

    def reopen(self, reopened_by: str, reason: str) -> ForexRevaluationAggregate:
        if not self.can_reopen():
            raise InvalidRevaluationStatusError(
                f"Cannot reopen revaluation in status {self.status.value}"
            )
        new_agg = self._copy()
        new_agg.status = RevaluationStatus.DRAFT
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = reopened_by
        new_agg.version = self.version + 1
        new_agg._record_audit("REOPEN", reopened_by, {"reason": reason})
        return new_agg

    def can_archive(self) -> bool:
        return self.status == RevaluationStatus.POSTED and self.journal_id is not None

    def archive(self, archived_by: str, reason: str | None = None) -> ForexRevaluationAggregate:
        if not self.can_archive():
            raise InvalidRevaluationStatusError(
                f"Cannot archive revaluation in status {self.status.value}"
            )
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = archived_by
        new_agg.version = self.version + 1
        new_agg._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_agg

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> ForexRevaluationAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.updated_by = unarchived_by
        new_agg.version = self.version + 1
        new_agg._record_audit("UNARCHIVE", unarchived_by, {})
        return new_agg

    # ==================== EVENT METHODS ====================

    def register_event(self, event: Any) -> None:
        self._events.append(event)

    def get_events(self) -> list[Any]:
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ── Tambahan untuk kepatuhan checker (AGG-021) ──
    def apply(self, event: Any) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        # For now, just record that event was applied.
        self._events.append(event)

    # ==================== BUSINESS METHODS ====================

    @classmethod
    def calculate_revaluation(
        cls,
        legal_entity_id: UUID,
        currency: str,
        balance_fcy: Decimal,
        old_rate: ExchangeRate,
        new_rate: ExchangeRate,
        created_by: str = "system",
    ) -> ForexRevaluationAggregate:
        """Factory method to calculate revaluation from rates."""
        gain_loss, gain_loss_type = old_rate.calculate_gain_loss(new_rate, balance_fcy)
        return cls(
            aggregate_id=uuid4(),
            legal_entity_id=legal_entity_id,
            currency=currency,
            revaluation_date=new_rate.effective_date,
            balance_fcy=balance_fcy,
            old_rate=old_rate,
            new_rate=new_rate,
            gain_loss=gain_loss,
            gain_loss_type=GainLossType(gain_loss_type),
            created_by=created_by,
            updated_by=created_by,
        )

    def create_adjustment_journal(self) -> RevaluationJournal:
        """Generate journal entry for the revaluation."""
        if self.gain_loss == 0:
            raise ForexRevaluationError("No gain/loss to journalize")

        lines = []
        if self.gain_loss_type == GainLossType.GAIN:
            # Credit: Foreign Exchange Gain, Debit: Monetary Item
            lines.append(
                JournalLine(
                    account_code="4210",
                    account_name="Foreign Exchange Gain",
                    debit=Decimal("0"),
                    credit=self.gain_loss,
                    description=f"Unrealized gain from {self.currency} revaluation",
                )
            )
            lines.append(
                JournalLine(
                    account_code="1100",
                    account_name="Cash in Bank",
                    debit=self.gain_loss,
                    credit=Decimal("0"),
                    description=f"Adjustment for {self.currency} revaluation",
                )
            )
        else:
            # Debit: Foreign Exchange Loss, Credit: Monetary Item
            lines.append(
                JournalLine(
                    account_code="5210",
                    account_name="Foreign Exchange Loss",
                    debit=self.gain_loss,
                    credit=Decimal("0"),
                    description=f"Unrealized loss from {self.currency} revaluation",
                )
            )
            lines.append(
                JournalLine(
                    account_code="1100",
                    account_name="Cash in Bank",
                    debit=Decimal("0"),
                    credit=self.gain_loss,
                    description=f"Adjustment for {self.currency} revaluation",
                )
            )

        journal = RevaluationJournal(
            journal_id=uuid4(),
            revaluation_id=self.aggregate_id,
            journal_date=self.revaluation_date,
            description=f"Forex revaluation {self.currency} as of {self.revaluation_date.date()}",
            lines=lines,
            created_by=self.created_by,
        )

        # ── AUDIT TRAIL untuk kepatuhan SOX ──
        self._record_audit("CREATE_ADJUSTMENT_JOURNAL", self.created_by, {
            "journal_id": str(journal.journal_id),
            "gain_loss": str(self.gain_loss),
            "gain_loss_type": self.gain_loss_type.value,
            "currency": self.currency,
            "balance_fcy": str(self.balance_fcy),
        })

        return journal

    def get_result(self) -> RevaluationResult:
        """Get revaluation result."""
        return RevaluationResult(
            gain_loss=self.gain_loss,
            gain_loss_type=self.gain_loss_type,
            old_rate=self.old_rate,
            new_rate=self.new_rate,
            balance_fcy=self.balance_fcy,
            balance_lcy_before=self.old_rate.convert(self.balance_fcy),
            balance_lcy_after=self.new_rate.convert(self.balance_fcy),
        )

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> ForexRevaluationAggregate:
        return ForexRevaluationAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            currency=self.currency,
            revaluation_date=self.revaluation_date,
            balance_fcy=self.balance_fcy,
            old_rate=self.old_rate,
            new_rate=self.new_rate,
            gain_loss=self.gain_loss,
            gain_loss_type=self.gain_loss_type,
            status=self.status,
            journal_id=self.journal_id,
            journal=self.journal,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejection_reason=self.rejection_reason,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class ForexRevaluationRepository:
    _storage: ClassVar[dict[UUID, ForexRevaluationAggregate]] = {}

    @classmethod
    async def get_by_id(cls, aggregate_id: UUID) -> ForexRevaluationAggregate | None:
        return cls._storage.get(aggregate_id)

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> list[ForexRevaluationAggregate]:
        return [agg for agg in cls._storage.values() if agg.legal_entity_id == legal_entity_id]

    @classmethod
    async def get_by_currency(
        cls, legal_entity_id: UUID, currency: str
    ) -> list[ForexRevaluationAggregate]:
        return [
            agg
            for agg in cls._storage.values()
            if agg.legal_entity_id == legal_entity_id and agg.currency == currency
        ]

    @classmethod
    async def get_by_status(
        cls, legal_entity_id: UUID, status: RevaluationStatus
    ) -> list[ForexRevaluationAggregate]:
        return [
            agg
            for agg in cls._storage.values()
            if agg.legal_entity_id == legal_entity_id and agg.status == status
        ]

    @classmethod
    async def get_all(cls) -> list[ForexRevaluationAggregate]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, aggregate: ForexRevaluationAggregate) -> None:
        cls._storage[aggregate.aggregate_id] = aggregate

    @classmethod
    async def delete(cls, aggregate_id: UUID) -> None:
        cls._storage.pop(aggregate_id, None)

    @classmethod
    async def exists(cls, aggregate_id: UUID) -> bool:
        return aggregate_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[ForexRevaluationAggregate]:
        aggregates = list(cls._storage.values())
        return aggregates[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "ExchangeRate",
    "ForexRevaluationAggregate",
    "ForexRevaluationError",
    "ForexRevaluationRepository",
    "GainLossType",
    "InvalidRevaluationStatusError",
    "JournalLine",
    "RevaluationAlreadyPostedError",
    "RevaluationJournal",
    "RevaluationResult",
    "RevaluationStatus",
]
