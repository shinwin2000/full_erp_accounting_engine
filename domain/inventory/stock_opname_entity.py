#!/usr/bin/env python3
"""
Module: stock_opname_entity.py
Layer: 6 - Domain / Inventory
Responsibility: Entitas stock opname fisik.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class StockOpnameStatus(Enum):
    """Status stock opname."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"

    @classmethod
    def from_string(cls, value: str) -> StockOpnameStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.PLANNED


class DiscrepancyType(Enum):
    """Tipe selisih stock opname."""

    SURPLUS = "surplus"
    SHORTAGE = "shortage"
    DAMAGE = "damage"
    EXPIRED = "expired"
    NONE = "none"

    @classmethod
    def from_string(cls, value: str) -> DiscrepancyType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.NONE


# === ALIAS FOR SERVICE IMPORT ===
OpnameStatus = StockOpnameStatus


@dataclass(kw_only=True)
class OpnameItem:
    """Item dalam stock opname."""

    item_id: UUID
    item_sku: str
    item_name: str
    system_quantity: Decimal
    physical_quantity: Decimal
    discrepancy: Decimal
    discrepancy_type: DiscrepancyType
    unit_cost: Decimal
    discrepancy_value: Decimal = Decimal("0")
    notes: str = ""
    counted_by: UUID | None = None
    counted_at: datetime | None = None

    def __post_init__(self):
        self.discrepancy_value = self.discrepancy * self.unit_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_sku": self.item_sku,
            "item_name": self.item_name,
            "system_quantity": str(self.system_quantity),
            "physical_quantity": str(self.physical_quantity),
            "discrepancy": str(self.discrepancy),
            "discrepancy_type": self.discrepancy_type.value,
            "unit_cost": str(self.unit_cost),
            "discrepancy_value": str(self.discrepancy_value),
            "notes": self.notes,
            "counted_by": str(self.counted_by) if self.counted_by else None,
            "counted_at": self.counted_at.isoformat() if self.counted_at else None,
        }


# === 2. STOCK OPNAME ENTITY ===


@dataclass(kw_only=True)
class StockOpnameEntity:
    """Entitas stock opname fisik."""

    opname_id: UUID
    opname_number: str
    warehouse_id: UUID
    warehouse_name: str
    opname_date: date
    status: StockOpnameStatus
    items: list[OpnameItem] = field(default_factory=list)
    performed_by: UUID
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejected_by: UUID | None = None
    rejected_at: datetime | None = None
    rejected_reason: str | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=uuid4)
    version: int = 1
    legal_entity_id: UUID | None = None
    warehouse_code: str | None = None

    @property
    def id(self) -> UUID:
        return self.opname_id

    @property
    def total_discrepancy(self) -> Decimal:
        return sum(i.discrepancy for i in self.items)

    @property
    def total_surplus(self) -> Decimal:
        return sum(
            i.discrepancy for i in self.items if i.discrepancy_type == DiscrepancyType.SURPLUS
        )

    @property
    def total_shortage(self) -> Decimal:
        return sum(
            i.discrepancy for i in self.items if i.discrepancy_type == DiscrepancyType.SHORTAGE
        )

    @property
    def total_discrepancy_value(self) -> Decimal:
        return sum(i.discrepancy_value for i in self.items)

    # ==================== BUSINESS METHODS ====================

    def start(self) -> StockOpnameEntity:
        """Start the stock opname."""
        if self.status != StockOpnameStatus.PLANNED:
            raise ValueError(f"Cannot start opname in status {self.status.value}")
        return StockOpnameEntity(
            opname_id=self.opname_id,
            opname_number=self.opname_number,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            opname_date=self.opname_date,
            status=StockOpnameStatus.IN_PROGRESS,
            items=self.items,
            performed_by=self.performed_by,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
        )

    def add_item(
        self,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        system_quantity: Decimal,
        physical_quantity: Decimal,
        unit_cost: Decimal,
        notes: str = "",
        counted_by: UUID | None = None,
    ) -> StockOpnameEntity:
        """Add or update an item in the opname."""
        discrepancy = physical_quantity - system_quantity
        if discrepancy > 0:
            discrepancy_type = DiscrepancyType.SURPLUS
        elif discrepancy < 0:
            discrepancy_type = DiscrepancyType.SHORTAGE
        else:
            discrepancy_type = DiscrepancyType.NONE

        opname_item = OpnameItem(
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            system_quantity=system_quantity,
            physical_quantity=physical_quantity,
            discrepancy=abs(discrepancy),
            discrepancy_type=discrepancy_type,
            unit_cost=unit_cost,
            notes=notes,
            counted_by=counted_by or self.performed_by,
            counted_at=datetime.now(UTC),
        )

        # Check if item already exists, replace it
        existing_indices = [i for i, it in enumerate(self.items) if it.item_id == item_id]
        if existing_indices:
            new_items = self.items.copy()
            new_items[existing_indices[0]] = opname_item
        else:
            new_items = self.items + [opname_item]

        return StockOpnameEntity(
            opname_id=self.opname_id,
            opname_number=self.opname_number,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            opname_date=self.opname_date,
            status=self.status,
            items=new_items,
            performed_by=self.performed_by,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
        )

    def add_items_batch(self, items: list[dict[str, Any]]) -> StockOpnameEntity:
        """Add multiple items at once."""
        result = self
        for item in items:
            result = result.add_item(
                item_id=item["item_id"],
                item_sku=item["item_sku"],
                item_name=item["item_name"],
                system_quantity=item["system_quantity"],
                physical_quantity=item["physical_quantity"],
                unit_cost=item["unit_cost"],
                notes=item.get("notes", ""),
                counted_by=item.get("counted_by"),
            )
        return result

    def complete(self) -> StockOpnameEntity:
        """Complete the stock opname."""
        if self.status != StockOpnameStatus.IN_PROGRESS:
            raise ValueError(f"Cannot complete opname in status {self.status.value}")
        return StockOpnameEntity(
            opname_id=self.opname_id,
            opname_number=self.opname_number,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            opname_date=self.opname_date,
            status=StockOpnameStatus.COMPLETED,
            items=self.items,
            performed_by=self.performed_by,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
        )

    def approve(self, approved_by: UUID) -> StockOpnameEntity:
        """Approve the stock opname."""
        if self.status != StockOpnameStatus.COMPLETED:
            raise ValueError(f"Cannot approve opname in status {self.status.value}")
        return StockOpnameEntity(
            opname_id=self.opname_id,
            opname_number=self.opname_number,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            opname_date=self.opname_date,
            status=StockOpnameStatus.APPROVED,
            items=self.items,
            performed_by=self.performed_by,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
        )

    def reject(self, rejected_by: UUID, reason: str) -> StockOpnameEntity:
        """Reject the stock opname."""
        if self.status not in (StockOpnameStatus.COMPLETED, StockOpnameStatus.IN_PROGRESS):
            raise ValueError(f"Cannot reject opname in status {self.status.value}")
        return StockOpnameEntity(
            opname_id=self.opname_id,
            opname_number=self.opname_number,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            opname_date=self.opname_date,
            status=StockOpnameStatus.REJECTED,
            items=self.items,
            performed_by=self.performed_by,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=rejected_by,
            rejected_at=datetime.now(UTC),
            rejected_reason=reason,
            notes=f"{self.notes}\nRejected: {reason}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
        )

    def cancel(self, cancelled_by: UUID, reason: str) -> StockOpnameEntity:
        """Cancel the stock opname."""
        if self.status not in (StockOpnameStatus.PLANNED, StockOpnameStatus.IN_PROGRESS):
            raise ValueError(f"Cannot cancel opname in status {self.status.value}")
        return StockOpnameEntity(
            opname_id=self.opname_id,
            opname_number=self.opname_number,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            opname_date=self.opname_date,
            status=StockOpnameStatus.CANCELLED,
            items=self.items,
            performed_by=self.performed_by,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            notes=f"{self.notes}\nCancelled: {reason} by {cancelled_by}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
            warehouse_code=self.warehouse_code,
        )

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create(
        cls,
        opname_number: str,
        warehouse_id: UUID,
        warehouse_name: str,
        opname_date: date,
        performed_by: UUID,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        notes: str = "",
    ) -> StockOpnameEntity:
        """Create a new stock opname."""
        return cls(
            opname_id=uuid4(),
            opname_number=opname_number,
            warehouse_id=warehouse_id,
            warehouse_name=warehouse_name,
            opname_date=opname_date,
            status=StockOpnameStatus.PLANNED,
            performed_by=performed_by,
            created_by=created_by or performed_by,
            legal_entity_id=legal_entity_id,
            notes=notes,
        )

    # ==================== SUMMARY ====================

    def get_summary(self) -> dict[str, Any]:
        return {
            "total_items": len(self.items),
            "total_discrepancy": str(self.total_discrepancy),
            "total_surplus": str(self.total_surplus),
            "total_shortage": str(self.total_shortage),
            "total_discrepancy_value": str(self.total_discrepancy_value),
            "items_with_discrepancy": len([i for i in self.items if i.discrepancy != 0]),
        }

    # ==================== DICTIONARY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "opname_id": str(self.opname_id),
            "opname_number": self.opname_number,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "warehouse_id": str(self.warehouse_id),
            "warehouse_name": self.warehouse_name,
            "warehouse_code": self.warehouse_code,
            "opname_date": self.opname_date.isoformat(),
            "status": self.status.value,
            "items_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
            "performed_by": str(self.performed_by),
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejected_reason": self.rejected_reason,
            "summary": self.get_summary(),
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StockOpnameEntity:
        items = []
        for item_data in data.get("items", []):
            items.append(
                OpnameItem(
                    item_id=UUID(item_data["item_id"]),
                    item_sku=item_data["item_sku"],
                    item_name=item_data["item_name"],
                    system_quantity=Decimal(item_data["system_quantity"]),
                    physical_quantity=Decimal(item_data["physical_quantity"]),
                    discrepancy=Decimal(item_data["discrepancy"]),
                    discrepancy_type=DiscrepancyType.from_string(item_data["discrepancy_type"]),
                    unit_cost=Decimal(item_data["unit_cost"]),
                    notes=item_data.get("notes", ""),
                    counted_by=UUID(item_data["counted_by"])
                    if item_data.get("counted_by")
                    else None,
                    counted_at=datetime.fromisoformat(item_data["counted_at"])
                    if item_data.get("counted_at")
                    else None,
                )
            )
        return cls(
            opname_id=UUID(data["opname_id"]),
            opname_number=data["opname_number"],
            warehouse_id=UUID(data["warehouse_id"]),
            warehouse_name=data["warehouse_name"],
            opname_date=date.fromisoformat(data["opname_date"]),
            status=StockOpnameStatus.from_string(data["status"]),
            items=items,
            performed_by=UUID(data["performed_by"]),
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            rejected_by=UUID(data["rejected_by"]) if data.get("rejected_by") else None,
            rejected_at=datetime.fromisoformat(data["rejected_at"])
            if data.get("rejected_at")
            else None,
            rejected_reason=data.get("rejected_reason"),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=UUID(data["created_by"]),
            version=data.get("version", 1),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            warehouse_code=data.get("warehouse_code"),
        )


# === 3. ALIAS FOR SERVICE LAYER ===

StockOpname = StockOpnameEntity


# === 4. REPOSITORY PROTOCOL ===


class StockOpnameRepository:
    """Repository protocol for StockOpnameEntity."""

    async def get_by_id(self, opname_id: UUID, legal_entity_id: UUID) -> StockOpnameEntity | None:
        raise NotImplementedError

    async def get_by_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        status: StockOpnameStatus | None = None,
    ) -> list[StockOpnameEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[StockOpnameEntity]:
        raise NotImplementedError

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[StockOpnameEntity]:
        raise NotImplementedError

    async def save(self, opname: StockOpnameEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, opname_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# === 5. EXPORTS ===

__all__ = [
    "DiscrepancyType",
    "OpnameItem",
    "OpnameStatus",
    "StockOpname",
    "StockOpnameEntity",
    "StockOpnameRepository",
    "StockOpnameStatus",
]
