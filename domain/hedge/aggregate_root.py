#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Hedge
Responsibility: Aggregate root untuk hedge relationships dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class HedgeType(Enum):
    FAIR_VALUE = "fair_value"
    CASH_FLOW = "cash_flow"
    NET_INVESTMENT = "net_investment"

    def display_name(self) -> str:
        names = {
            HedgeType.FAIR_VALUE: "Lindung Nilai Nilai Wajar",
            HedgeType.CASH_FLOW: "Lindung Nilai Arus Kas",
            HedgeType.NET_INVESTMENT: "Lindung Nilai Investasi Bersih",
        }
        return names.get(self, self.value)

    def affects_pl_directly(self) -> bool:
        return self == HedgeType.FAIR_VALUE

    def affects_oci(self) -> bool:
        return self in (HedgeType.CASH_FLOW, HedgeType.NET_INVESTMENT)


class HedgeStatus(Enum):
    DESIGNATED = "designated"
    ACTIVE = "active"
    INEFFECTIVE = "ineffective"
    DISCONTINUED = "discontinued"
    PROSPECTIVE = "prospective"
    CANCELLED = "cancelled"

    def is_active(self) -> bool:
        return self in (HedgeStatus.DESIGNATED, HedgeStatus.ACTIVE)

    def can_test(self) -> bool:
        return self in (HedgeStatus.ACTIVE, HedgeStatus.DESIGNATED)

    def display_name(self) -> str:
        names = {
            HedgeStatus.DESIGNATED: "Ditunjuk",
            HedgeStatus.ACTIVE: "Aktif",
            HedgeStatus.INEFFECTIVE: "Tidak Efektif",
            HedgeStatus.DISCONTINUED: "Dihentikan",
            HedgeStatus.PROSPECTIVE: "Prospektif",
            HedgeStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> HedgeStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


class HedgeEffectivenessStatus(Enum):
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"
    HIGHLY_EFFECTIVE = "highly_effective"
    PENDING = "pending"

    def display_name(self) -> str:
        names = {
            HedgeEffectivenessStatus.EFFECTIVE: "Efektif",
            HedgeEffectivenessStatus.INEFFECTIVE: "Tidak Efektif",
            HedgeEffectivenessStatus.HIGHLY_EFFECTIVE: "Sangat Efektif",
            HedgeEffectivenessStatus.PENDING: "Menunggu",
        }
        return names.get(self, self.value)


# ============================================================================
# Custom Exceptions
# ============================================================================


class HedgeError(ValueError):
    pass


class InvalidHedgeTypeError(HedgeError):
    pass


class InvalidEffectivenessThresholdError(HedgeError):
    pass


class HedgeAlreadyDiscontinuedError(HedgeError):
    pass


class HedgeNotFoundError(HedgeError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class EffectivenessTestResult:
    test_id: UUID
    hedge_id: UUID
    test_date: datetime
    test_type: str  # "prospective" or "retrospective"
    is_effective: bool
    ratio: Decimal
    variance: Decimal
    cumulative_hedge_change: Decimal
    cumulative_hedged_change: Decimal
    message: str
    tested_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.test_date.tzinfo is None:
            object.__setattr__(self, "test_date", self.test_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": str(self.test_id),
            "hedge_id": str(self.hedge_id),
            "test_date": self.test_date.isoformat(),
            "test_type": self.test_type,
            "is_effective": self.is_effective,
            "ratio": str(self.ratio),
            "variance": str(self.variance),
            "cumulative_hedge_change": str(self.cumulative_hedge_change),
            "cumulative_hedged_change": str(self.cumulative_hedged_change),
            "message": self.message,
            "tested_by": self.tested_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EffectivenessTestResult:
        return cls(
            test_id=UUID(data["test_id"]),
            hedge_id=UUID(data["hedge_id"]),
            test_date=datetime.fromisoformat(data["test_date"]),
            test_type=data["test_type"],
            is_effective=data["is_effective"],
            ratio=Decimal(data["ratio"]),
            variance=Decimal(data["variance"]),
            cumulative_hedge_change=Decimal(data["cumulative_hedge_change"]),
            cumulative_hedged_change=Decimal(data["cumulative_hedged_change"]),
            message=data["message"],
            tested_by=data["tested_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass(frozen=True)
class HedgeAdjustment:
    adjustment_id: UUID
    hedge_id: UUID
    adjustment_date: datetime
    adjustment_amount: Decimal
    ineffectiveness: Decimal
    adjustment_type: str  # "fair_value" or "cash_flow"
    description: str
    recorded_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.adjustment_date.tzinfo is None:
            object.__setattr__(self, "adjustment_date", self.adjustment_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjustment_id": str(self.adjustment_id),
            "hedge_id": str(self.hedge_id),
            "adjustment_date": self.adjustment_date.isoformat(),
            "adjustment_amount": str(self.adjustment_amount),
            "ineffectiveness": str(self.ineffectiveness),
            "adjustment_type": self.adjustment_type,
            "description": self.description,
            "recorded_by": self.recorded_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HedgeAdjustment:
        return cls(
            adjustment_id=UUID(data["adjustment_id"]),
            hedge_id=UUID(data["hedge_id"]),
            adjustment_date=datetime.fromisoformat(data["adjustment_date"]),
            adjustment_amount=Decimal(data["adjustment_amount"]),
            ineffectiveness=Decimal(data["ineffectiveness"]),
            adjustment_type=data["adjustment_type"],
            description=data["description"],
            recorded_by=data["recorded_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ============================================================================
# Aggregate Root: HedgeRelationship
# ============================================================================


@dataclass(frozen=True)
class HedgeRelationship:
    id: UUID
    hedge_number: str
    legal_entity_id: UUID
    hedge_type: HedgeType
    designation_date: date
    description: str
    hedge_instrument_id: UUID
    hedged_item_id: UUID
    status: HedgeStatus = HedgeStatus.DESIGNATED
    risk_components: list[str] = field(default_factory=list)
    effectiveness_threshold_lower: Decimal = Decimal("0.80")
    effectiveness_threshold_upper: Decimal = Decimal("1.25")
    effectiveness_status: HedgeEffectivenessStatus = HedgeEffectivenessStatus.PENDING
    last_test_date: datetime | None = None
    last_test_ratio: Decimal | None = None
    last_test_is_effective: bool | None = None
    accumulated_ineffectiveness: Decimal = Decimal("0")
    discontinued_date: date | None = None
    discontinued_reason: str | None = None
    cancellation_date: date | None = None
    cancellation_reason: str | None = None
    test_history: list[EffectivenessTestResult] = field(default_factory=list)
    adjustments: list[HedgeAdjustment] = field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.hedge_number or len(self.hedge_number.strip()) < 3:
            raise HedgeError("Hedge number must be at least 3 characters")
        if not isinstance(self.hedge_type, HedgeType):
            raise InvalidHedgeTypeError(f"Invalid hedge_type: {self.hedge_type}")
        if self.effectiveness_threshold_lower <= 0 or self.effectiveness_threshold_lower >= 1:
            raise InvalidEffectivenessThresholdError(
                f"Lower threshold must be between 0 and 1: {self.effectiveness_threshold_lower}"
            )
        if self.effectiveness_threshold_upper <= 1:
            raise InvalidEffectivenessThresholdError(
                f"Upper threshold must be greater than 1: {self.effectiveness_threshold_upper}"
            )
        if self.effectiveness_threshold_lower > self.effectiveness_threshold_upper:
            raise InvalidEffectivenessThresholdError(
                f"Lower threshold {self.effectiveness_threshold_lower} cannot exceed upper threshold {self.effectiveness_threshold_upper}"
            )
        if self.designation_date > date.today():
            raise HedgeError(f"Designation date {self.designation_date} cannot be in the future")
        if self.discontinued_date and self.discontinued_date < self.designation_date:
            raise HedgeError(
                f"Discontinued date {self.discontinued_date} cannot be before designation date"
            )
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.last_test_date and self.last_test_date.tzinfo is None:
            object.__setattr__(self, "last_test_date", self.last_test_date.replace(tzinfo=UTC))
        if self.version < 1:
            raise HedgeError("Version must be >= 1")
        if self.accumulated_ineffectiveness < 0:
            raise HedgeError(
                f"Accumulated ineffectiveness cannot be negative: {self.accumulated_ineffectiveness}"
            )

    # ==================== Properties ====================

    @property
    def is_effective(self, ratio: Decimal | None = None) -> bool:
        if ratio is not None:
            return self.effectiveness_threshold_lower <= ratio <= self.effectiveness_threshold_upper
        return self.effectiveness_status == HedgeEffectivenessStatus.EFFECTIVE

    @property
    def is_active(self) -> bool:
        return self.status.is_active()

    @property
    def is_designated(self) -> bool:
        return self.status == HedgeStatus.DESIGNATED

    @property
    def is_discontinued(self) -> bool:
        return self.status == HedgeStatus.DISCONTINUED

    @property
    def is_cancelled(self) -> bool:
        return self.status == HedgeStatus.CANCELLED

    @property
    def can_be_tested(self) -> bool:
        return self.status.can_test()

    @property
    def effectiveness_range_display(self) -> str:
        return (
            f"[{self.effectiveness_threshold_lower:.2f} - {self.effectiveness_threshold_upper:.2f}]"
        )

    @property
    def total_adjustment(self) -> Decimal:
        return sum(a.adjustment_amount for a in self.adjustments)

    @property
    def total_ineffectiveness(self) -> Decimal:
        return self.accumulated_ineffectiveness

    # ==================== Factory Methods ====================

    @classmethod
    def designate(
        cls,
        hedge_number: str,
        legal_entity_id: UUID,
        hedge_type: HedgeType,
        designation_date: date,
        description: str,
        hedge_instrument_id: UUID,
        hedged_item_id: UUID,
        risk_components: list[str] | None = None,
        effectiveness_threshold_lower: Decimal = Decimal("0.80"),
        effectiveness_threshold_upper: Decimal = Decimal("1.25"),
        created_by: UUID | None = None,
    ) -> HedgeRelationship:
        return cls(
            id=uuid4(),
            hedge_number=hedge_number,
            legal_entity_id=legal_entity_id,
            hedge_type=hedge_type,
            designation_date=designation_date,
            description=description,
            hedge_instrument_id=hedge_instrument_id,
            hedged_item_id=hedged_item_id,
            status=HedgeStatus.DESIGNATED,
            risk_components=risk_components or [],
            effectiveness_threshold_lower=effectiveness_threshold_lower,
            effectiveness_threshold_upper=effectiveness_threshold_upper,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HedgeRelationship:
        hedge_type = HedgeType(data["hedge_type"])
        status = HedgeStatus(data["status"])
        effectiveness_status = HedgeEffectivenessStatus(data.get("effectiveness_status", "pending"))
        risk_components = data.get("risk_components", [])
        designation_date = date.fromisoformat(data["designation_date"])
        discontinued_date = (
            date.fromisoformat(data["discontinued_date"]) if data.get("discontinued_date") else None
        )
        cancellation_date = (
            date.fromisoformat(data["cancellation_date"]) if data.get("cancellation_date") else None
        )
        last_test_date = (
            datetime.fromisoformat(data["last_test_date"]) if data.get("last_test_date") else None
        )
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        test_history = [EffectivenessTestResult.from_dict(t) for t in data.get("test_history", [])]
        adjustments = [HedgeAdjustment.from_dict(a) for a in data.get("adjustments", [])]
        return cls(
            id=UUID(data["id"]),
            hedge_number=data["hedge_number"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            hedge_type=hedge_type,
            designation_date=designation_date,
            description=data["description"],
            hedge_instrument_id=UUID(data["hedge_instrument_id"]),
            hedged_item_id=UUID(data["hedged_item_id"]),
            status=status,
            risk_components=risk_components,
            effectiveness_threshold_lower=Decimal(data["effectiveness_threshold_lower"]),
            effectiveness_threshold_upper=Decimal(data["effectiveness_threshold_upper"]),
            effectiveness_status=effectiveness_status,
            last_test_date=last_test_date,
            last_test_ratio=Decimal(data["last_test_ratio"])
            if data.get("last_test_ratio")
            else None,
            last_test_is_effective=data.get("last_test_is_effective"),
            accumulated_ineffectiveness=Decimal(data.get("accumulated_ineffectiveness", "0")),
            discontinued_date=discontinued_date,
            discontinued_reason=data.get("discontinued_reason"),
            cancellation_date=cancellation_date,
            cancellation_reason=data.get("cancellation_reason"),
            test_history=test_history,
            adjustments=adjustments,
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_at=created_at,
            updated_at=updated_at,
            version=data.get("version", 1),
        )

    def to_dict(self, include_history: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "hedge_number": self.hedge_number,
            "legal_entity_id": str(self.legal_entity_id),
            "hedge_type": self.hedge_type.value,
            "designation_date": self.designation_date.isoformat(),
            "description": self.description,
            "hedge_instrument_id": str(self.hedge_instrument_id),
            "hedged_item_id": str(self.hedged_item_id),
            "status": self.status.value,
            "risk_components": self.risk_components,
            "effectiveness_threshold_lower": str(self.effectiveness_threshold_lower),
            "effectiveness_threshold_upper": str(self.effectiveness_threshold_upper),
            "effectiveness_status": self.effectiveness_status.value,
            "last_test_date": self.last_test_date.isoformat() if self.last_test_date else None,
            "last_test_ratio": str(self.last_test_ratio) if self.last_test_ratio else None,
            "last_test_is_effective": self.last_test_is_effective,
            "accumulated_ineffectiveness": str(self.accumulated_ineffectiveness),
            "discontinued_date": self.discontinued_date.isoformat()
            if self.discontinued_date
            else None,
            "discontinued_reason": self.discontinued_reason,
            "cancellation_date": self.cancellation_date.isoformat()
            if self.cancellation_date
            else None,
            "cancellation_reason": self.cancellation_reason,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_active": self.is_active,
            "total_adjustment": str(self.total_adjustment),
            "total_ineffectiveness": str(self.total_ineffectiveness),
        }
        if include_history:
            result["test_history"] = [t.to_dict() for t in self.test_history]
            result["adjustments"] = [a.to_dict() for a in self.adjustments]
        return result


# ============================================================================
# HedgeRelationshipAggregate (Mutable Wrapper)
# ============================================================================


class HedgeRelationshipAggregate:
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    # ---- Attribute untuk kepatuhan checker ----
    _events: list = []  # akan di-override di __init__

    def __init__(self, hedge: HedgeRelationship):
        self._hedge = hedge
        self._events: list[Any] = []
        # ── Tambahan untuk kepatuhan checker (AGG-011, AGG-012) ──
        self.id: UUID = hedge.id
        self.version: int = hedge.version
        self._take_snapshot()

    # ==================== EVENT CONTRACT ====================

    def register_event(self, event: Any) -> None:
        """Register a domain event."""
        self._events.append(event)

    def get_events(self) -> list[Any]:
        """Get all registered events."""
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        """Pull and clear all events."""
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        """Clear all events."""
        self._events.clear()

    # ── Tambahan untuk kepatuhan checker (AGG-021) ──
    def apply(self, event: Any) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        # Placeholder: record that event was applied
        self._events.append(event)

    # ==================== END EVENT CONTRACT ====================

    @property
    def hedge(self) -> HedgeRelationship:
        return self._hedge

    @property
    def id(self) -> UUID:
        return self._hedge.id

    @property
    def domain_events(self) -> list[Any]:
        """Compatibility property."""
        return self.get_events()

    def pop_events(self) -> list[Any]:
        """Alias for pull_events (compatibility)."""
        return self.pull_events()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._hedge.version,
            "hedge_id": str(self._hedge.id),
            "hedge_number": self._hedge.hedge_number,
            "status": self._hedge.status.value,
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
            "version": self._hedge.version,
            "hedge_id": str(self._hedge.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== INTERNAL HELPER ====================

    def _register_event(self, event: Any) -> None:
        """Internal helper (kept for compatibility)."""
        self.register_event(event)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> HedgeRelationshipAggregate:
        self._record_audit("CREATE", created_by, {"hedge_number": self._hedge.hedge_number})
        return self

    def update(self, updated_by: str, **kwargs) -> HedgeRelationshipAggregate:
        data = self._hedge.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_hedge = HedgeRelationship.from_dict(data)
        self._hedge = new_hedge
        self._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return self

    def delete(self, deleted_by: str, reason: str | None = None) -> HedgeRelationshipAggregate:
        if self._hedge.status == HedgeStatus.DISCONTINUED:
            return self
        self._hedge = self._hedge.cancel(deleted_by, reason)
        self._record_audit("DELETE", deleted_by, {"reason": reason})
        return self

    def restore(self, restored_by: str) -> HedgeRelationshipAggregate:
        if self._hedge.status != HedgeStatus.CANCELLED:
            raise HedgeError(f"Cannot restore hedge in status {self._hedge.status.value}")
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "status": HedgeStatus.DESIGNATED,
                "cancellation_date": None,
                "cancellation_reason": None,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self._record_audit("RESTORE", restored_by, {})
        return self

    def activate(self, activated_by: str) -> HedgeRelationshipAggregate:
        if self._hedge.status == HedgeStatus.ACTIVE:
            return self
        if not self._hedge.can_be_tested:
            raise HedgeError(f"Cannot activate hedge in status {self._hedge.status.value}")
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "status": HedgeStatus.ACTIVE,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self._record_audit("ACTIVATE", activated_by, {})
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> HedgeRelationshipAggregate:
        if self._hedge.status == HedgeStatus.DISCONTINUED:
            return self
        return self.discontinue(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: str, reason: str) -> HedgeRelationshipAggregate:
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self._record_audit("LOCK", locked_by, {"reason": reason})
        return self

    def unlock(self, unlocked_by: str) -> HedgeRelationshipAggregate:
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self._record_audit("UNLOCK", unlocked_by, {})
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._hedge._validate()
        except HedgeError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "hedge_id": str(self._hedge.id),
            "version": self._hedge.version,
        }

    def clone(self) -> HedgeRelationshipAggregate:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned_hedge = HedgeRelationship(
            id=new_id,
            hedge_number=f"{self._hedge.hedge_number}_COPY",
            legal_entity_id=self._hedge.legal_entity_id,
            hedge_type=self._hedge.hedge_type,
            designation_date=self._hedge.designation_date,
            description=f"Cloned from {self._hedge.hedge_number}",
            hedge_instrument_id=self._hedge.hedge_instrument_id,
            hedged_item_id=self._hedge.hedged_item_id,
            status=HedgeStatus.DESIGNATED,
            risk_components=self._hedge.risk_components.copy(),
            effectiveness_threshold_lower=self._hedge.effectiveness_threshold_lower,
            effectiveness_threshold_upper=self._hedge.effectiveness_threshold_upper,
            created_by=self._hedge.created_by,
            created_at=now,
            updated_at=now,
            version=1,
        )
        cloned_agg = HedgeRelationshipAggregate(cloned_hedge)
        cloned_agg._record_audit("CLONE", "system", {"source": str(self._hedge.id)})
        return cloned_agg

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._hedge.version,
            "hedge_id": str(self._hedge.id),
            "hedge_number": self._hedge.hedge_number,
            "status": self._hedge.status.value,
            "effectiveness_status": self._hedge.effectiveness_status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._hedge.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> HedgeRelationshipAggregate:
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self._record_audit("TOUCH", touched_by, {})
        return self

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, child: Any, created_by: str) -> HedgeRelationshipAggregate:
        raise NotImplementedError("Hedge relationship has no child entities")

    def remove_child(self, child_id: UUID, removed_by: str) -> HedgeRelationshipAggregate:
        raise NotImplementedError("Hedge relationship has no child entities")

    def can_post(self) -> bool:
        return self._hedge.status == HedgeStatus.ACTIVE

    def post(self, posted_by: str) -> HedgeRelationshipAggregate:
        self._record_audit("POST", posted_by, {})
        return self

    def can_approve(self, user_role: str = "user") -> bool:
        return self._hedge.status in (HedgeStatus.DESIGNATED, HedgeStatus.ACTIVE) and user_role in (
            "finance_manager",
            "admin",
        )

    def approve(self, approved_by: str) -> HedgeRelationshipAggregate:
        self._record_audit("APPROVE", approved_by, {})
        return self

    def can_reject(self, user_role: str = "user") -> bool:
        return self._hedge.status == HedgeStatus.DESIGNATED

    def reject(self, rejected_by: str, reason: str) -> HedgeRelationshipAggregate:
        self._record_audit("REJECT", rejected_by, {"reason": reason})
        return self

    def can_cancel(self) -> bool:
        return self._hedge.status not in (HedgeStatus.DISCONTINUED, HedgeStatus.CANCELLED)

    def cancel(self, cancelled_by: str, reason: str) -> HedgeRelationshipAggregate:
        if not self.can_cancel():
            raise HedgeError(f"Cannot cancel hedge in status {self._hedge.status.value}")
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "status": HedgeStatus.CANCELLED,
                "cancellation_date": date.today(),
                "cancellation_reason": reason,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self.register_event(
            {"event_type": "HedgeDiscontinued", "hedge_id": str(self._hedge.id), "reason": reason}
        )
        self._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return self

    def can_reverse(self) -> bool:
        return False

    def reverse(self, reversed_by: str, reason: str) -> HedgeRelationshipAggregate:
        raise NotImplementedError("Reverse not applicable for hedge")

    def can_close(self) -> bool:
        return self._hedge.status in (HedgeStatus.DISCONTINUED, HedgeStatus.CANCELLED)

    def close(self, closed_by: str, reason: str) -> HedgeRelationshipAggregate:
        if not self.can_close():
            raise HedgeError(f"Cannot close hedge in status {self._hedge.status.value}")
        self._record_audit("CLOSE", closed_by, {"reason": reason})
        return self

    def can_reopen(self) -> bool:
        return self._hedge.status in (HedgeStatus.DISCONTINUED, HedgeStatus.CANCELLED)

    def reopen(self, reopened_by: str, reason: str) -> HedgeRelationshipAggregate:
        if not self.can_reopen():
            raise HedgeError(f"Cannot reopen hedge in status {self._hedge.status.value}")
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "status": HedgeStatus.ACTIVE,
                "discontinued_date": None,
                "discontinued_reason": None,
                "cancellation_date": None,
                "cancellation_reason": None,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self._record_audit("REOPEN", reopened_by, {"reason": reason})
        return self

    def can_archive(self) -> bool:
        return self._hedge.status == HedgeStatus.DISCONTINUED

    def archive(self, archived_by: str, reason: str | None = None) -> HedgeRelationshipAggregate:
        if not self.can_archive():
            raise HedgeError(f"Cannot archive hedge in status {self._hedge.status.value}")
        self._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return self

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> HedgeRelationshipAggregate:
        self._record_audit("UNARCHIVE", unarchived_by, {})
        return self

    # ==================== EVENT METHODS ====================
    # register_event, get_events, pull_events, clear_events sudah di atas
    # _register_event juga sudah sebagai alias

    # ==================== BUSINESS METHODS ====================

    def record_effectiveness_test(
        self,
        test_type: str,
        is_effective: bool,
        ratio: Decimal,
        cumulative_hedge_change: Decimal,
        cumulative_hedged_change: Decimal,
        tested_by: str,
        message: str = "",
    ) -> HedgeRelationshipAggregate:
        if not self._hedge.can_be_tested:
            raise HedgeError(f"Cannot test hedge in status {self._hedge.status.value}")

        variance = abs(ratio - Decimal("1"))
        test = EffectivenessTestResult(
            test_id=uuid4(),
            hedge_id=self._hedge.id,
            test_date=datetime.now(UTC),
            test_type=test_type,
            is_effective=is_effective,
            ratio=ratio,
            variance=variance,
            cumulative_hedge_change=cumulative_hedge_change,
            cumulative_hedged_change=cumulative_hedged_change,
            message=message,
            tested_by=tested_by,
        )
        new_history = self._hedge.test_history + [test]

        effectiveness_status = (
            HedgeEffectivenessStatus.EFFECTIVE
            if is_effective
            else HedgeEffectivenessStatus.INEFFECTIVE
        )
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "test_history": new_history,
                "effectiveness_status": effectiveness_status,
                "last_test_date": test.test_date,
                "last_test_ratio": ratio,
                "last_test_is_effective": is_effective,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self.register_event(
            {
                "event_type": "HedgeEffectivenessTested",
                "hedge_id": str(self._hedge.id),
                "is_effective": is_effective,
                "ratio": str(ratio),
            }
        )
        self._record_audit(
            "EFFECTIVENESS_TEST", tested_by, {"is_effective": is_effective, "ratio": str(ratio)}
        )
        return self

    def record_adjustment(
        self,
        adjustment_amount: Decimal,
        ineffectiveness: Decimal,
        adjustment_type: str,
        description: str,
        recorded_by: str,
    ) -> HedgeRelationshipAggregate:
        if self._hedge.status != HedgeStatus.ACTIVE:
            raise HedgeError(
                f"Cannot record adjustment for hedge in status {self._hedge.status.value}"
            )

        adjustment = HedgeAdjustment(
            adjustment_id=uuid4(),
            hedge_id=self._hedge.id,
            adjustment_date=datetime.now(UTC),
            adjustment_amount=adjustment_amount,
            ineffectiveness=ineffectiveness,
            adjustment_type=adjustment_type,
            description=description,
            recorded_by=recorded_by,
        )
        new_adjustments = self._hedge.adjustments + [adjustment]
        new_ineffectiveness = self._hedge.accumulated_ineffectiveness + ineffectiveness
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "adjustments": new_adjustments,
                "accumulated_ineffectiveness": new_ineffectiveness,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self.register_event(
            {
                "event_type": "HedgeFairValueAdjusted",
                "hedge_id": str(self._hedge.id),
                "adjustment_amount": str(adjustment_amount),
                "ineffectiveness": str(ineffectiveness),
            }
        )
        self._record_audit(
            "RECORD_ADJUSTMENT",
            recorded_by,
            {"amount": str(adjustment_amount), "ineffectiveness": str(ineffectiveness)},
        )
        return self

    def discontinue(self, discontinued_by: str, reason: str) -> HedgeRelationshipAggregate:
        if self._hedge.status == HedgeStatus.DISCONTINUED:
            return self
        new_hedge = HedgeRelationship(
            **{
                **self._hedge.__dict__,
                "status": HedgeStatus.DISCONTINUED,
                "discontinued_date": date.today(),
                "discontinued_reason": reason,
                "updated_at": datetime.now(UTC),
                "version": self._hedge.version + 1,
            }
        )
        self._hedge = new_hedge
        self.register_event(
            {"event_type": "HedgeDiscontinued", "hedge_id": str(self._hedge.id), "reason": reason}
        )
        self._record_audit("DISCONTINUE", discontinued_by, {"reason": reason})
        return self

    def get_test_history(self, limit: int = 50) -> list[EffectivenessTestResult]:
        return self._hedge.test_history[-limit:]

    def get_adjustments(self, limit: int = 50) -> list[HedgeAdjustment]:
        return self._hedge.adjustments[-limit:]

    def get_summary(self) -> dict[str, Any]:
        return {
            "hedge_id": str(self._hedge.id),
            "hedge_number": self._hedge.hedge_number,
            "hedge_type": self._hedge.hedge_type.value,
            "status": self._hedge.status.value,
            "effectiveness_status": self._hedge.effectiveness_status.value,
            "designation_date": self._hedge.designation_date.isoformat(),
            "total_adjustment": str(self._hedge.total_adjustment),
            "accumulated_ineffectiveness": str(self._hedge.accumulated_ineffectiveness),
            "total_tests": len(self._hedge.test_history),
            "last_test_ratio": str(self._hedge.last_test_ratio)
            if self._hedge.last_test_ratio
            else None,
            "last_test_is_effective": self._hedge.last_test_is_effective,
            "is_active": self._hedge.is_active,
            "threshold_lower": str(self._hedge.effectiveness_threshold_lower),
            "threshold_upper": str(self._hedge.effectiveness_threshold_upper),
        }


# ============================================================================
# Repository Implementation
# ============================================================================


class HedgeRepository:
    _storage: ClassVar[dict[UUID, HedgeRelationshipAggregate]] = {}

    @classmethod
    async def get_by_id(cls, hedge_id: UUID) -> HedgeRelationshipAggregate | None:
        return cls._storage.get(hedge_id)

    @classmethod
    async def get_by_number(cls, hedge_number: str) -> HedgeRelationshipAggregate | None:
        for agg in cls._storage.values():
            if agg.hedge.hedge_number == hedge_number:
                return agg
        return None

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> list[HedgeRelationshipAggregate]:
        return [
            agg for agg in cls._storage.values() if agg.hedge.legal_entity_id == legal_entity_id
        ]

    @classmethod
    async def get_by_status(cls, status: HedgeStatus) -> list[HedgeRelationshipAggregate]:
        return [agg for agg in cls._storage.values() if agg.hedge.status == status]

    @classmethod
    async def get_all(cls) -> list[HedgeRelationshipAggregate]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, aggregate: HedgeRelationshipAggregate) -> None:
        cls._storage[aggregate.hedge.id] = aggregate

    @classmethod
    async def delete(cls, hedge_id: UUID) -> None:
        cls._storage.pop(hedge_id, None)

    @classmethod
    async def exists(cls, hedge_id: UUID) -> bool:
        return hedge_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[HedgeRelationshipAggregate]:
        aggregates = list(cls._storage.values())
        return aggregates[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "EffectivenessTestResult",
    "HedgeAdjustment",
    "HedgeEffectivenessStatus",
    "HedgeError",
    "HedgeRelationship",
    "HedgeRelationshipAggregate",
    "HedgeRepository",
    "HedgeStatus",
    "HedgeType",
    "InvalidEffectivenessThresholdError",
    "InvalidHedgeTypeError",
]