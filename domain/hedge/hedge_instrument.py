#!/usr/bin/env python3
"""
Module: hedge_instrument.py
Layer: Domain / Hedge
Responsibility: Hedge instrument (derivative, forward, etc.) with all entity dasar methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.hedge.aggregate_root import HedgeType

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class InstrumentType(Enum):
    FORWARD = "forward"
    FUTURE = "future"
    SWAP = "swap"
    OPTION = "option"
    OTHER = "other"

    def display_name(self) -> str:
        names = {
            InstrumentType.FORWARD: "Kontrak Forward",
            InstrumentType.FUTURE: "Kontrak Berjangka",
            InstrumentType.SWAP: "Swap",
            InstrumentType.OPTION: "Opsi",
            InstrumentType.OTHER: "Lainnya",
        }
        return names.get(self, self.value)

    def is_derivative(self) -> bool:
        """Check if instrument is a derivative."""
        return self in (
            InstrumentType.FORWARD,
            InstrumentType.FUTURE,
            InstrumentType.SWAP,
            InstrumentType.OPTION,
        )

    def has_premium(self) -> bool:
        """Does this instrument type require premium payment?"""
        return self == InstrumentType.OPTION

    @classmethod
    def from_string(cls, value: str) -> InstrumentType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


class InstrumentStatus(Enum):
    ACTIVE = "active"
    EXERCISED = "exercised"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"

    def is_active(self) -> bool:
        return self == InstrumentStatus.ACTIVE

    def display_name(self) -> str:
        names = {
            InstrumentStatus.ACTIVE: "Aktif",
            InstrumentStatus.EXERCISED: "Dieksekusi",
            InstrumentStatus.EXPIRED: "Kadaluarsa",
            InstrumentStatus.TERMINATED: "Dihentikan",
            InstrumentStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> InstrumentStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class HedgeInstrumentError(ValueError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class InstrumentFairValueHistory:
    history_id: UUID
    instrument_id: UUID
    valuation_date: datetime
    fair_value: Decimal
    valuation_method: str
    valued_by: str
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.valuation_date.tzinfo is None:
            object.__setattr__(self, "valuation_date", self.valuation_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "history_id": str(self.history_id),
            "instrument_id": str(self.instrument_id),
            "valuation_date": self.valuation_date.isoformat(),
            "fair_value": str(self.fair_value),
            "valuation_method": self.valuation_method,
            "valued_by": self.valued_by,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstrumentFairValueHistory:
        return cls(
            history_id=UUID(data["history_id"]),
            instrument_id=UUID(data["instrument_id"]),
            valuation_date=datetime.fromisoformat(data["valuation_date"]),
            fair_value=Decimal(data["fair_value"]),
            valuation_method=data["valuation_method"],
            valued_by=data["valued_by"],
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ============================================================================
# Entity: HedgeInstrument
# ============================================================================


@dataclass(frozen=True)
class HedgeInstrument:
    id: UUID
    instrument_number: str
    instrument_type: InstrumentType
    legal_entity_id: UUID
    notional: Decimal
    currency: str
    hedge_type: HedgeType
    counterparty: str
    start_date: date | None = None
    maturity_date: date | None = None
    strike_price: Decimal | None = None
    premium_paid: Decimal = Decimal("0")
    premium_paid_date: date | None = None
    fair_value: Decimal = Decimal("0")
    accumulated_oci: Decimal = Decimal("0")
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    hedged_item_id: UUID | None = None
    description: str = ""
    fair_value_history: list[InstrumentFairValueHistory] = field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.instrument_number or len(self.instrument_number.strip()) < 3:
            raise HedgeInstrumentError("Instrument number must be at least 3 characters")
        if not isinstance(self.instrument_type, InstrumentType):
            raise HedgeInstrumentError(f"Invalid instrument_type: {self.instrument_type}")
        if not isinstance(self.hedge_type, HedgeType):
            raise HedgeInstrumentError(f"Invalid hedge_type: {self.hedge_type}")
        if self.notional <= 0:
            raise HedgeInstrumentError(f"Notional must be positive: {self.notional}")
        if not self.currency or len(self.currency) != 3:
            raise HedgeInstrumentError(f"Invalid currency: {self.currency}")
        if not self.counterparty or len(self.counterparty.strip()) < 2:
            raise HedgeInstrumentError("Counterparty name must be at least 2 characters")
        if self.start_date and self.start_date > date.today():
            raise HedgeInstrumentError(f"Start date {self.start_date} cannot be in the future")
        if self.maturity_date and self.maturity_date < (self.start_date or date.today()):
            raise HedgeInstrumentError(
                f"Maturity date {self.maturity_date} cannot be before start date"
            )
        if self.premium_paid < 0:
            raise HedgeInstrumentError(f"Premium paid cannot be negative: {self.premium_paid}")
        if self.instrument_type.has_premium() and self.premium_paid == 0:
            logger.warning(f"Option instrument {self.instrument_number} has zero premium")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.version < 1:
            raise HedgeInstrumentError("Version must be >= 1")

    # ==================== Properties ====================

    @property
    def is_active(self) -> bool:
        return self.status.is_active()

    @property
    def is_derivative(self) -> bool:
        return self.instrument_type.is_derivative()

    @property
    def has_premium(self) -> bool:
        return self.instrument_type.has_premium()

    @property
    def is_expired(self, as_of: date | None = None) -> bool:
        check_date = as_of or date.today()
        if self.maturity_date:
            return check_date > self.maturity_date
        return False

    @property
    def days_to_maturity(self, as_of: date | None = None) -> int:
        check_date = as_of or date.today()
        if self.maturity_date:
            delta = self.maturity_date - check_date
            return max(0, delta.days)
        return 0

    @property
    def total_fair_value_change(self) -> Decimal:
        if not self.fair_value_history:
            return Decimal("0")
        first_fv = self.fair_value_history[0].fair_value
        return self.fair_value - first_fv

    # ==================== Factory Methods ====================

    @classmethod
    def create(
        cls,
        instrument_number: str,
        instrument_type: InstrumentType,
        legal_entity_id: UUID,
        notional: Decimal,
        currency: str,
        hedge_type: HedgeType,
        counterparty: str,
        start_date: date | None = None,
        maturity_date: date | None = None,
        strike_price: Decimal | None = None,
        premium_paid: Decimal = Decimal("0"),
        description: str = "",
        created_by: UUID | None = None,
    ) -> HedgeInstrument:
        return cls(
            id=uuid4(),
            instrument_number=instrument_number,
            instrument_type=instrument_type,
            legal_entity_id=legal_entity_id,
            notional=notional,
            currency=currency,
            hedge_type=hedge_type,
            counterparty=counterparty,
            start_date=start_date,
            maturity_date=maturity_date,
            strike_price=strike_price,
            premium_paid=premium_paid,
            description=description,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HedgeInstrument:
        instrument_type = InstrumentType.from_string(data["instrument_type"])
        if instrument_type is None:
            raise HedgeInstrumentError(f"Invalid instrument_type: {data['instrument_type']}")
        hedge_type = HedgeType(data["hedge_type"])
        status = (
            InstrumentStatus.from_string(data.get("status", "active")) or InstrumentStatus.ACTIVE
        )
        start_date = date.fromisoformat(data["start_date"]) if data.get("start_date") else None
        maturity_date = (
            date.fromisoformat(data["maturity_date"]) if data.get("maturity_date") else None
        )
        premium_paid_date = (
            date.fromisoformat(data["premium_paid_date"]) if data.get("premium_paid_date") else None
        )
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        fair_value_history = [
            InstrumentFairValueHistory.from_dict(h) for h in data.get("fair_value_history", [])
        ]
        return cls(
            id=UUID(data["id"]),
            instrument_number=data["instrument_number"],
            instrument_type=instrument_type,
            legal_entity_id=UUID(data["legal_entity_id"]),
            notional=Decimal(data["notional"]),
            currency=data["currency"],
            hedge_type=hedge_type,
            counterparty=data["counterparty"],
            start_date=start_date,
            maturity_date=maturity_date,
            strike_price=Decimal(data["strike_price"]) if data.get("strike_price") else None,
            premium_paid=Decimal(data.get("premium_paid", "0")),
            premium_paid_date=premium_paid_date,
            fair_value=Decimal(data.get("fair_value", "0")),
            accumulated_oci=Decimal(data.get("accumulated_oci", "0")),
            status=status,
            hedged_item_id=UUID(data["hedged_item_id"]) if data.get("hedged_item_id") else None,
            description=data.get("description", ""),
            fair_value_history=fair_value_history,
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_at=created_at,
            updated_at=updated_at,
            version=data.get("version", 1),
        )

    def to_dict(self, include_history: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "instrument_number": self.instrument_number,
            "instrument_type": self.instrument_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "notional": str(self.notional),
            "currency": self.currency,
            "hedge_type": self.hedge_type.value,
            "counterparty": self.counterparty,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
            "strike_price": str(self.strike_price) if self.strike_price else None,
            "premium_paid": str(self.premium_paid),
            "premium_paid_date": self.premium_paid_date.isoformat()
            if self.premium_paid_date
            else None,
            "fair_value": str(self.fair_value),
            "accumulated_oci": str(self.accumulated_oci),
            "status": self.status.value,
            "hedged_item_id": str(self.hedged_item_id) if self.hedged_item_id else None,
            "description": self.description,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_active": self.is_active,
            "is_derivative": self.is_derivative,
            "days_to_maturity": self.days_to_maturity,
        }
        if include_history:
            result["fair_value_history"] = [h.to_dict() for h in self.fair_value_history]
        return result

    # ==================== ENTITY DASAR METHODS ====================

    def stamp_create_audit(self, created_by: str) -> HedgeInstrument:
        """Rename dari create() semula -- nama itu bentrok dengan
        factory classmethod create() di atas dan membuatnya jadi dead
        code (Python: definisi terakhir menang). Method ini cuma stempel
        audit trail pada instance yang sudah ada, BUKAN factory."""
        self._record_audit("CREATE", created_by, {"instrument_number": self.instrument_number})
        return self

    def update(self, updated_by: str, **kwargs) -> HedgeInstrument:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_instrument = self.from_dict(data)
        new_instrument._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_instrument

    def delete(self, deleted_by: str, reason: str | None = None) -> HedgeInstrument:
        if self.status != InstrumentStatus.ACTIVE:
            raise HedgeInstrumentError(f"Cannot delete instrument in status {self.status.value}")
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "status": InstrumentStatus.CANCELLED,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_instrument

    def restore(self, restored_by: str) -> HedgeInstrument:
        if self.status != InstrumentStatus.CANCELLED:
            raise HedgeInstrumentError(f"Cannot restore instrument in status {self.status.value}")
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "status": InstrumentStatus.ACTIVE,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("RESTORE", restored_by, {})
        return new_instrument

    def activate(self, activated_by: str) -> HedgeInstrument:
        if self.status == InstrumentStatus.ACTIVE:
            return self
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "status": InstrumentStatus.ACTIVE,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("ACTIVATE", activated_by, {})
        return new_instrument

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> HedgeInstrument:
        if self.status != InstrumentStatus.ACTIVE:
            raise HedgeInstrumentError(
                f"Cannot deactivate instrument in status {self.status.value}"
            )
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "status": InstrumentStatus.TERMINATED,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_instrument

    def lock(self, locked_by: str, reason: str) -> HedgeInstrument:
        new_instrument = HedgeInstrument(
            **{**self.__dict__, "updated_at": datetime.now(UTC), "version": self.version + 1}
        )
        new_instrument._record_audit("LOCK", locked_by, {"reason": reason})
        return new_instrument

    def unlock(self, unlocked_by: str) -> HedgeInstrument:
        new_instrument = HedgeInstrument(
            **{**self.__dict__, "updated_at": datetime.now(UTC), "version": self.version + 1}
        )
        new_instrument._record_audit("UNLOCK", unlocked_by, {})
        return new_instrument

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except HedgeInstrumentError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "instrument_id": str(self.id),
            "version": self.version,
        }

    def clone(self) -> HedgeInstrument:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = HedgeInstrument(
            id=new_id,
            instrument_number=f"{self.instrument_number}_COPY",
            instrument_type=self.instrument_type,
            legal_entity_id=self.legal_entity_id,
            notional=self.notional,
            currency=self.currency,
            hedge_type=self.hedge_type,
            counterparty=self.counterparty,
            start_date=self.start_date,
            maturity_date=self.maturity_date,
            strike_price=self.strike_price,
            premium_paid=self.premium_paid,
            description=f"Cloned from {self.instrument_number}",
            created_by=self.created_by,
            created_at=now,
            updated_at=now,
            version=1,
        )
        cloned._record_audit(
            "CLONE", str(self.created_by) if self.created_by else "system", {"source": str(self.id)}
        )
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "instrument_id": str(self.id),
            "instrument_number": self.instrument_number,
            "fair_value": str(self.fair_value),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return getattr(self, "_audit_trail", [])[-limit:]

    def touch(self, touched_by: str) -> HedgeInstrument:
        new_instrument = HedgeInstrument(
            **{**self.__dict__, "updated_at": datetime.now(UTC), "version": self.version + 1}
        )
        new_instrument._record_audit("TOUCH", touched_by, {})
        return new_instrument

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        if not hasattr(self, "_audit_trail"):
            object.__setattr__(self, "_audit_trail", [])
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "instrument_id": str(self.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== BUSINESS METHODS ====================

    def designate(self, hedged_item_id: UUID, designated_by: str) -> HedgeInstrument:
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "hedged_item_id": hedged_item_id,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit(
            "DESIGNATE", designated_by, {"hedged_item_id": str(hedged_item_id)}
        )
        return new_instrument

    def record_fair_value(
        self,
        new_fair_value: Decimal,
        valuation_date: datetime,
        valuation_method: str,
        valued_by: str,
        notes: str = "",
    ) -> HedgeInstrument:
        if valuation_date.tzinfo is None:
            valuation_date = valuation_date.replace(tzinfo=UTC)
        change = new_fair_value - self.fair_value
        history_entry = InstrumentFairValueHistory(
            history_id=uuid4(),
            instrument_id=self.id,
            valuation_date=valuation_date,
            fair_value=new_fair_value,
            valuation_method=valuation_method,
            valued_by=valued_by,
            notes=notes,
        )
        new_history = self.fair_value_history + [history_entry]

        if self.hedge_type == HedgeType.CASH_FLOW:
            new_accumulated_oci = self.accumulated_oci + change
            new_instrument = HedgeInstrument(
                **{
                    **self.__dict__,
                    "fair_value": new_fair_value,
                    "accumulated_oci": new_accumulated_oci,
                    "fair_value_history": new_history,
                    "updated_at": datetime.now(UTC),
                    "version": self.version + 1,
                }
            )
        else:
            new_instrument = HedgeInstrument(
                **{
                    **self.__dict__,
                    "fair_value": new_fair_value,
                    "fair_value_history": new_history,
                    "updated_at": datetime.now(UTC),
                    "version": self.version + 1,
                }
            )
        new_instrument._record_audit(
            "RECORD_FAIR_VALUE",
            valued_by,
            {"old_fair_value": str(self.fair_value), "new_fair_value": str(new_fair_value)},
        )
        return new_instrument

    def record_oci_reclassification(self, amount: Decimal, reclassified_by: str) -> HedgeInstrument:
        if self.hedge_type != HedgeType.CASH_FLOW:
            raise HedgeInstrumentError("OCI reclassification only applies to cash flow hedges")
        if amount > self.accumulated_oci:
            raise HedgeInstrumentError(
                f"Reclassification amount {amount} exceeds accumulated OCI {self.accumulated_oci}"
            )
        new_accumulated_oci = self.accumulated_oci - amount
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "accumulated_oci": new_accumulated_oci,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("RECLASSIFY_OCI", reclassified_by, {"amount": str(amount)})
        return new_instrument

    def exercise(self, exercised_by: str) -> HedgeInstrument:
        if self.instrument_type != InstrumentType.OPTION:
            raise HedgeInstrumentError("Only options can be exercised")
        if self.status != InstrumentStatus.ACTIVE:
            raise HedgeInstrumentError(f"Cannot exercise instrument in status {self.status.value}")
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "status": InstrumentStatus.EXERCISED,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("EXERCISE", exercised_by, {})
        return new_instrument

    def expire(self) -> HedgeInstrument:
        if self.status != InstrumentStatus.ACTIVE:
            return self
        new_instrument = HedgeInstrument(
            **{
                **self.__dict__,
                "status": InstrumentStatus.EXPIRED,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_instrument._record_audit("EXPIRE", "system", {"maturity_date": str(self.maturity_date)})
        return new_instrument

    def get_fair_value_at_date(self, target_date: datetime) -> Decimal | None:
        for history in reversed(self.fair_value_history):
            if history.valuation_date <= target_date:
                return history.fair_value
        return None


# ============================================================================
# Repository Implementation
# ============================================================================


class HedgeInstrumentRepository:
    _storage: ClassVar[dict[UUID, HedgeInstrument]] = {}

    @classmethod
    async def get_by_id(cls, instrument_id: UUID, legal_entity_id: UUID) -> HedgeInstrument | None:
        return cls._storage.get(instrument_id)

    @classmethod
    async def get_by_number(
        cls, instrument_number: str, legal_entity_id: UUID
    ) -> HedgeInstrument | None:
        for inst in cls._storage.values():
            if inst.instrument_number == instrument_number:
                return inst
        return None

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> list[HedgeInstrument]:
        return [inst for inst in cls._storage.values() if inst.legal_entity_id == legal_entity_id]

    @classmethod
    async def get_by_type(
        cls, instrument_type: InstrumentType, legal_entity_id: UUID
    ) -> list[HedgeInstrument]:
        return [
            inst
            for inst in cls._storage.values()
            if inst.legal_entity_id == legal_entity_id and inst.instrument_type == instrument_type
        ]

    @classmethod
    async def get_active(cls, legal_entity_id: UUID) -> list[HedgeInstrument]:
        return [
            inst
            for inst in cls._storage.values()
            if inst.legal_entity_id == legal_entity_id and inst.is_active
        ]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[HedgeInstrument]:
        return [inst for inst in cls._storage.values() if inst.legal_entity_id == legal_entity_id]

    @classmethod
    async def save(cls, instrument: HedgeInstrument, legal_entity_id: UUID) -> None:
        cls._storage[instrument.id] = instrument

    @classmethod
    async def delete(cls, instrument_id: UUID, legal_entity_id: UUID) -> None:
        cls._storage.pop(instrument_id, None)

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        cls._storage.clear()


__all__ = [
    "HedgeInstrument",
    "HedgeInstrumentError",
    "HedgeInstrumentRepository",
    "InstrumentFairValueHistory",
    "InstrumentStatus",
    "InstrumentType",
]
