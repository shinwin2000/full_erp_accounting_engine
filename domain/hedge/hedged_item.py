#!/usr/bin/env python3
"""
Module: hedged_item.py
Layer: Domain / Hedge
Responsibility: Hedged item (asset, liability, forecast transaction, etc.) with all entity dasar methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class HedgedItemType(Enum):
    INVENTORY = "inventory"
    FIXED_ASSET = "fixed_asset"
    LOAN = "loan"
    FORECAST_SALE = "forecast_sale"
    FORECAST_PURCHASE = "forecast_purchase"
    OTHER = "other"

    def display_name(self) -> str:
        names = {
            HedgedItemType.INVENTORY: "Persediaan",
            HedgedItemType.FIXED_ASSET: "Aset Tetap",
            HedgedItemType.LOAN: "Pinjaman",
            HedgedItemType.FORECAST_SALE: "Penjualan yang Diharapkan",
            HedgedItemType.FORECAST_PURCHASE: "Pembelian yang Diharapkan",
            HedgedItemType.OTHER: "Lainnya",
        }
        return names.get(self, self.value)

    def is_forecast(self) -> bool:
        return self in (HedgedItemType.FORECAST_SALE, HedgedItemType.FORECAST_PURCHASE)

    def is_existing_asset_liability(self) -> bool:
        return self in (HedgedItemType.INVENTORY, HedgedItemType.FIXED_ASSET, HedgedItemType.LOAN)

    @classmethod
    def from_string(cls, value: str) -> HedgedItemType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


class HedgedItemStatus(Enum):
    ACTIVE = "active"
    SETTLED = "settled"
    CANCELLED = "cancelled"

    def is_active(self) -> bool:
        return self == HedgedItemStatus.ACTIVE

    def display_name(self) -> str:
        names = {
            HedgedItemStatus.ACTIVE: "Aktif",
            HedgedItemStatus.SETTLED: "Diselesaikan",
            HedgedItemStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> HedgedItemStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class HedgedItemError(ValueError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class HedgedItemAdjustment:
    adjustment_id: UUID
    hedged_item_id: UUID
    adjustment_date: datetime
    adjustment_amount: Decimal
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
            "hedged_item_id": str(self.hedged_item_id),
            "adjustment_date": self.adjustment_date.isoformat(),
            "adjustment_amount": str(self.adjustment_amount),
            "adjustment_type": self.adjustment_type,
            "description": self.description,
            "recorded_by": self.recorded_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HedgedItemAdjustment:
        return cls(
            adjustment_id=UUID(data["adjustment_id"]),
            hedged_item_id=UUID(data["hedged_item_id"]),
            adjustment_date=datetime.fromisoformat(data["adjustment_date"]),
            adjustment_amount=Decimal(data["adjustment_amount"]),
            adjustment_type=data["adjustment_type"],
            description=data["description"],
            recorded_by=data["recorded_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ============================================================================
# Entity: HedgedItem
# ============================================================================


@dataclass(frozen=True)
class HedgedItem:
    id: UUID
    item_number: str
    item_type: HedgedItemType
    legal_entity_id: UUID
    description: str
    carrying_amount: Decimal
    currency: str
    reference_id: UUID | None = None
    risk_exposure: str = "interest_rate"
    status: HedgedItemStatus = HedgedItemStatus.ACTIVE
    adjustments: list[HedgedItemAdjustment] = field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.item_number or len(self.item_number.strip()) < 3:
            raise HedgedItemError("Item number must be at least 3 characters")
        if not isinstance(self.item_type, HedgedItemType):
            raise HedgedItemError(f"Invalid item_type: {self.item_type}")
        if not self.description or len(self.description.strip()) < 2:
            raise HedgedItemError("Description must be at least 2 characters")
        if self.carrying_amount < 0:
            raise HedgedItemError(f"Carrying amount cannot be negative: {self.carrying_amount}")
        if not self.currency or len(self.currency) != 3:
            raise HedgedItemError(f"Invalid currency: {self.currency}")
        if not self.risk_exposure or len(self.risk_exposure.strip()) < 2:
            raise HedgedItemError("Risk exposure must be specified")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.version < 1:
            raise HedgedItemError("Version must be >= 1")

    # ==================== Properties ====================

    @property
    def is_active(self) -> bool:
        return self.status.is_active()

    @property
    def is_forecast(self) -> bool:
        return self.item_type.is_forecast()

    @property
    def is_existing(self) -> bool:
        return self.item_type.is_existing_asset_liability()

    @property
    def total_adjustment(self) -> Decimal:
        return sum(a.adjustment_amount for a in self.adjustments)

    @property
    def adjusted_carrying_amount(self) -> Decimal:
        return self.carrying_amount + self.total_adjustment

    # ==================== Factory Methods ====================

    @classmethod
    def create(
        cls,
        item_number: str,
        item_type: HedgedItemType,
        legal_entity_id: UUID,
        description: str,
        carrying_amount: Decimal,
        currency: str,
        reference_id: UUID | None = None,
        risk_exposure: str = "interest_rate",
        created_by: UUID | None = None,
    ) -> HedgedItem:
        return cls(
            id=uuid4(),
            item_number=item_number,
            item_type=item_type,
            legal_entity_id=legal_entity_id,
            description=description,
            carrying_amount=carrying_amount,
            currency=currency,
            reference_id=reference_id,
            risk_exposure=risk_exposure,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HedgedItem:
        item_type = HedgedItemType.from_string(data["item_type"])
        if item_type is None:
            raise HedgedItemError(f"Invalid item_type: {data['item_type']}")
        status = (
            HedgedItemStatus.from_string(data.get("status", "active")) or HedgedItemStatus.ACTIVE
        )
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        adjustments = [HedgedItemAdjustment.from_dict(a) for a in data.get("adjustments", [])]
        return cls(
            id=UUID(data["id"]),
            item_number=data["item_number"],
            item_type=item_type,
            legal_entity_id=UUID(data["legal_entity_id"]),
            description=data["description"],
            carrying_amount=Decimal(data["carrying_amount"]),
            currency=data["currency"],
            reference_id=UUID(data["reference_id"]) if data.get("reference_id") else None,
            risk_exposure=data.get("risk_exposure", "interest_rate"),
            status=status,
            adjustments=adjustments,
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_at=created_at,
            updated_at=updated_at,
            version=data.get("version", 1),
        )

    def to_dict(self, include_history: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "item_number": self.item_number,
            "item_type": self.item_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "description": self.description,
            "carrying_amount": str(self.carrying_amount),
            "currency": self.currency,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "risk_exposure": self.risk_exposure,
            "status": self.status.value,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_active": self.is_active,
            "is_forecast": self.is_forecast,
            "is_existing": self.is_existing,
            "total_adjustment": str(self.total_adjustment),
            "adjusted_carrying_amount": str(self.adjusted_carrying_amount),
        }
        if include_history:
            result["adjustments"] = [a.to_dict() for a in self.adjustments]
        return result

    # ==================== ENTITY DASAR METHODS ====================

    def stamp_create_audit(self, created_by: str) -> HedgedItem:
        """Rename dari create() semula -- nama itu bentrok dengan
        factory classmethod create() di atas dan membuatnya jadi dead
        code (Python: definisi terakhir menang). Method ini cuma stempel
        audit trail pada instance yang sudah ada, BUKAN factory."""
        self._record_audit("CREATE", created_by, {"item_number": self.item_number})
        return self

    def update(self, updated_by: str, **kwargs) -> HedgedItem:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_item = self.from_dict(data)
        new_item._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_item

    def delete(self, deleted_by: str, reason: str | None = None) -> HedgedItem:
        if self.status != HedgedItemStatus.ACTIVE:
            raise HedgedItemError(f"Cannot delete item in status {self.status.value}")
        new_item = HedgedItem(
            **{
                **self.__dict__,
                "status": HedgedItemStatus.CANCELLED,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_item._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_item

    def restore(self, restored_by: str) -> HedgedItem:
        if self.status != HedgedItemStatus.CANCELLED:
            raise HedgedItemError(f"Cannot restore item in status {self.status.value}")
        new_item = HedgedItem(
            **{
                **self.__dict__,
                "status": HedgedItemStatus.ACTIVE,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_item._record_audit("RESTORE", restored_by, {})
        return new_item

    def activate(self, activated_by: str) -> HedgedItem:
        if self.status == HedgedItemStatus.ACTIVE:
            return self
        new_item = HedgedItem(
            **{
                **self.__dict__,
                "status": HedgedItemStatus.ACTIVE,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_item._record_audit("ACTIVATE", activated_by, {})
        return new_item

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> HedgedItem:
        if self.status != HedgedItemStatus.ACTIVE:
            raise HedgedItemError(f"Cannot deactivate item in status {self.status.value}")
        new_item = HedgedItem(
            **{
                **self.__dict__,
                "status": HedgedItemStatus.SETTLED,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_item._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_item

    def lock(self, locked_by: str, reason: str) -> HedgedItem:
        new_item = HedgedItem(
            **{**self.__dict__, "updated_at": datetime.now(UTC), "version": self.version + 1}
        )
        new_item._record_audit("LOCK", locked_by, {"reason": reason})
        return new_item

    def unlock(self, unlocked_by: str) -> HedgedItem:
        new_item = HedgedItem(
            **{**self.__dict__, "updated_at": datetime.now(UTC), "version": self.version + 1}
        )
        new_item._record_audit("UNLOCK", unlocked_by, {})
        return new_item

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except HedgedItemError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "item_id": str(self.id),
            "version": self.version,
        }

    def clone(self) -> HedgedItem:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = HedgedItem(
            id=new_id,
            item_number=f"{self.item_number}_COPY",
            item_type=self.item_type,
            legal_entity_id=self.legal_entity_id,
            description=f"Cloned from {self.item_number}",
            carrying_amount=self.carrying_amount,
            currency=self.currency,
            reference_id=self.reference_id,
            risk_exposure=self.risk_exposure,
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
            "item_id": str(self.id),
            "item_number": self.item_number,
            "carrying_amount": str(self.carrying_amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return getattr(self, "_audit_trail", [])[-limit:]

    def touch(self, touched_by: str) -> HedgedItem:
        new_item = HedgedItem(
            **{**self.__dict__, "updated_at": datetime.now(UTC), "version": self.version + 1}
        )
        new_item._record_audit("TOUCH", touched_by, {})
        return new_item

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        if not hasattr(self, "_audit_trail"):
            object.__setattr__(self, "_audit_trail", [])
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "item_id": str(self.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== BUSINESS METHODS ====================

    def record_adjustment(
        self,
        adjustment_amount: Decimal,
        adjustment_type: str,
        description: str,
        recorded_by: str,
    ) -> HedgedItem:
        adjustment = HedgedItemAdjustment(
            adjustment_id=uuid4(),
            hedged_item_id=self.id,
            adjustment_date=datetime.now(UTC),
            adjustment_amount=adjustment_amount,
            adjustment_type=adjustment_type,
            description=description,
            recorded_by=recorded_by,
        )
        new_adjustments = [*self.adjustments, adjustment]
        new_item = HedgedItem(
            **{
                **self.__dict__,
                "adjustments": new_adjustments,
                "updated_at": datetime.now(UTC),
                "version": self.version + 1,
            }
        )
        new_item._record_audit(
            "RECORD_ADJUSTMENT",
            recorded_by,
            {"amount": str(adjustment_amount), "type": adjustment_type},
        )
        return new_item

    def settle(self, settled_by: str, settlement_amount: Decimal) -> HedgedItem:
        if self.status != HedgedItemStatus.ACTIVE:
            raise HedgedItemError(f"Cannot settle item in status {self.status.value}")
        return self.record_adjustment(
            settlement_amount, "settlement", f"Settled by {settled_by}", settled_by
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class HedgedItemRepository:
    _storage: ClassVar[dict[UUID, HedgedItem]] = {}

    @classmethod
    async def get_by_id(cls, item_id: UUID, legal_entity_id: UUID) -> HedgedItem | None:
        return cls._storage.get(item_id)

    @classmethod
    async def get_by_number(cls, item_number: str, legal_entity_id: UUID) -> HedgedItem | None:
        for item in cls._storage.values():
            if item.item_number == item_number:
                return item
        return None

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> list[HedgedItem]:
        return [item for item in cls._storage.values() if item.legal_entity_id == legal_entity_id]

    @classmethod
    async def get_by_type(
        cls, item_type: HedgedItemType, legal_entity_id: UUID
    ) -> list[HedgedItem]:
        return [
            item
            for item in cls._storage.values()
            if item.legal_entity_id == legal_entity_id and item.item_type == item_type
        ]

    @classmethod
    async def get_active(cls, legal_entity_id: UUID) -> list[HedgedItem]:
        return [
            item
            for item in cls._storage.values()
            if item.legal_entity_id == legal_entity_id and item.is_active
        ]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[HedgedItem]:
        return [item for item in cls._storage.values() if item.legal_entity_id == legal_entity_id]

    @classmethod
    async def save(cls, item: HedgedItem, legal_entity_id: UUID) -> None:
        cls._storage[item.id] = item

    @classmethod
    async def delete(cls, item_id: UUID, legal_entity_id: UUID) -> None:
        cls._storage.pop(item_id, None)

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        cls._storage.clear()


__all__ = [
    "HedgedItem",
    "HedgedItemAdjustment",
    "HedgedItemError",
    "HedgedItemRepository",
    "HedgedItemStatus",
    "HedgedItemType",
]
