#!/usr/bin/env python3
"""
Module: inter_warehouse_transfer_entity.py
Layer: 6 - Domain / Inventory
Responsibility: Transfer antar gudang.
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


class TransferStatus(Enum):
    """Status transfer antar gudang."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @classmethod
    def from_string(cls, value: str) -> TransferStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


class TransferPriority(Enum):
    """Prioritas transfer."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

    @classmethod
    def from_string(cls, value: str) -> TransferPriority:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.NORMAL


@dataclass(kw_only=True)
class TransferItem:
    """Item dalam transfer."""

    item_id: UUID
    item_sku: str
    item_name: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    batch_number: str | None = None
    expiry_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_sku": self.item_sku,
            "item_name": self.item_name,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "total_value": str(self.total_value),
            "batch_number": self.batch_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
        }


# === 2. INTER WAREHOUSE TRANSFER ENTITY ===


@dataclass(kw_only=True)
class InterWarehouseTransferEntity:
    """Entitas transfer antar gudang."""

    transfer_id: UUID
    transfer_number: str
    source_warehouse_id: UUID
    source_warehouse_name: str
    destination_warehouse_id: UUID
    destination_warehouse_name: str
    transfer_date: date
    priority: TransferPriority
    status: TransferStatus
    items: list[TransferItem] = field(default_factory=list)
    requested_by: UUID
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejected_by: UUID | None = None
    rejected_at: datetime | None = None
    rejected_reason: str | None = None
    shipped_by: UUID | None = None
    shipped_at: datetime | None = None
    received_by: UUID | None = None
    received_at: datetime | None = None
    completed_by: UUID | None = None
    completed_at: datetime | None = None
    reason: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=uuid4)
    version: int = 1
    legal_entity_id: UUID | None = None

    # Denormalized fields for convenience
    quantity: Decimal = Decimal(0)
    unit_cost: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)

    def __post_init__(self):
        self._recalculate_denorm()

    def _recalculate_denorm(self) -> None:
        """Recalculate denormalized totals."""
        if self.items:
            total_qty = sum(i.quantity for i in self.items)
            total_val = sum(i.total_value for i in self.items)
            avg_cost = total_val / total_qty if total_qty > 0 else Decimal(0)
            object.__setattr__(self, "quantity", total_qty)
            object.__setattr__(self, "total_value", total_val)
            object.__setattr__(self, "unit_cost", avg_cost)

    @property
    def id(self) -> UUID:
        return self.transfer_id

    @property
    def from_warehouse(self) -> str:
        return self.source_warehouse_name

    @property
    def to_warehouse(self) -> str:
        return self.destination_warehouse_name

    # ==================== BUSINESS METHODS ====================

    def add_item(
        self,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        quantity: Decimal,
        unit_cost: Decimal,
        batch_number: str | None = None,
        expiry_date: date | None = None,
    ) -> InterWarehouseTransferEntity:
        """Add an item to the transfer."""
        if self.status not in (TransferStatus.DRAFT, TransferStatus.PENDING):
            raise ValueError(f"Cannot add item to transfer in status {self.status.value}")
        if quantity <= 0:
            raise ValueError("Transfer quantity must be positive")
        total_val = quantity * unit_cost
        transfer_item = TransferItem(
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            quantity=quantity,
            unit_cost=unit_cost,
            total_value=total_val,
            batch_number=batch_number,
            expiry_date=expiry_date,
        )
        new_items = self.items + [transfer_item]
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=self.status,
            items=new_items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def remove_item(self, item_id: UUID) -> InterWarehouseTransferEntity:
        """Remove an item from the transfer."""
        if self.status not in (TransferStatus.DRAFT, TransferStatus.PENDING):
            raise ValueError(f"Cannot remove item from transfer in status {self.status.value}")
        new_items = [i for i in self.items if i.item_id != item_id]
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=self.status,
            items=new_items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def submit(self) -> InterWarehouseTransferEntity:
        """Submit transfer for approval."""
        if self.status != TransferStatus.DRAFT:
            raise ValueError(f"Cannot submit transfer in status {self.status.value}")
        if not self.items:
            raise ValueError("Cannot submit transfer with no items")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.PENDING,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def approve(self, approved_by: UUID) -> InterWarehouseTransferEntity:
        """Approve the transfer."""
        if self.status != TransferStatus.PENDING:
            raise ValueError(f"Cannot approve transfer in status {self.status.value}")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.APPROVED,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def reject(self, rejected_by: UUID, reason: str) -> InterWarehouseTransferEntity:
        """Reject the transfer."""
        if self.status != TransferStatus.PENDING:
            raise ValueError(f"Cannot reject transfer in status {self.status.value}")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.REJECTED,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=rejected_by,
            rejected_at=datetime.now(UTC),
            rejected_reason=reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=f"{self.notes}\nRejected: {reason}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def ship(self, shipped_by: UUID) -> InterWarehouseTransferEntity:
        """Mark transfer as shipped."""
        if self.status != TransferStatus.APPROVED:
            raise ValueError(f"Cannot ship transfer in status {self.status.value}")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.IN_TRANSIT,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=shipped_by,
            shipped_at=datetime.now(UTC),
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def receive(self, received_by: UUID) -> InterWarehouseTransferEntity:
        """Mark transfer as received."""
        if self.status != TransferStatus.IN_TRANSIT:
            raise ValueError(f"Cannot receive transfer in status {self.status.value}")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.RECEIVED,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=received_by,
            received_at=datetime.now(UTC),
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def complete(self, completed_by: UUID) -> InterWarehouseTransferEntity:
        """Complete the transfer."""
        if self.status != TransferStatus.RECEIVED:
            raise ValueError(f"Cannot complete transfer in status {self.status.value}")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.COMPLETED,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=completed_by,
            completed_at=datetime.now(UTC),
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    def cancel(self, cancelled_by: UUID, reason: str) -> InterWarehouseTransferEntity:
        """Cancel the transfer."""
        if self.status in (TransferStatus.COMPLETED, TransferStatus.CANCELLED):
            raise ValueError(f"Cannot cancel transfer in status {self.status.value}")
        return InterWarehouseTransferEntity(
            transfer_id=self.transfer_id,
            transfer_number=self.transfer_number,
            source_warehouse_id=self.source_warehouse_id,
            source_warehouse_name=self.source_warehouse_name,
            destination_warehouse_id=self.destination_warehouse_id,
            destination_warehouse_name=self.destination_warehouse_name,
            transfer_date=self.transfer_date,
            priority=self.priority,
            status=TransferStatus.CANCELLED,
            items=self.items,
            requested_by=self.requested_by,
            requested_at=self.requested_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejected_reason=self.rejected_reason,
            shipped_by=self.shipped_by,
            shipped_at=self.shipped_at,
            received_by=self.received_by,
            received_at=self.received_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            reason=f"{self.reason}\nCancelled: {reason}",
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
            legal_entity_id=self.legal_entity_id,
        )

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create(
        cls,
        transfer_number: str,
        source_warehouse_id: UUID,
        source_warehouse_name: str,
        destination_warehouse_id: UUID,
        destination_warehouse_name: str,
        transfer_date: date,
        requested_by: UUID,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        priority: TransferPriority = TransferPriority.NORMAL,
        reason: str = "",
    ) -> InterWarehouseTransferEntity:
        """Create a new transfer."""
        return cls(
            transfer_id=uuid4(),
            transfer_number=transfer_number,
            source_warehouse_id=source_warehouse_id,
            source_warehouse_name=source_warehouse_name,
            destination_warehouse_id=destination_warehouse_id,
            destination_warehouse_name=destination_warehouse_name,
            transfer_date=transfer_date,
            priority=priority,
            status=TransferStatus.DRAFT,
            requested_by=requested_by,
            created_by=created_by or requested_by,
            legal_entity_id=legal_entity_id,
            reason=reason,
        )

    # ==================== VALIDATION ====================

    def validate(self) -> list[str]:
        """Validate invariants."""
        errors = []
        if not self.items:
            errors.append("Transfer must have at least one item")
        for item in self.items:
            if item.quantity <= 0:
                errors.append(f"Item {item.item_sku} has invalid quantity: {item.quantity}")
            if item.unit_cost < 0:
                errors.append(f"Item {item.item_sku} has negative unit cost: {item.unit_cost}")
        if self.source_warehouse_id == self.destination_warehouse_id:
            errors.append("Source and destination warehouses cannot be the same")
        return errors

    # ==================== DICTIONARY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "transfer_id": str(self.transfer_id),
            "transfer_number": self.transfer_number,
            "source_warehouse_id": str(self.source_warehouse_id),
            "source_warehouse_name": self.source_warehouse_name,
            "destination_warehouse_id": str(self.destination_warehouse_id),
            "destination_warehouse_name": self.destination_warehouse_name,
            "transfer_date": self.transfer_date.isoformat(),
            "priority": self.priority.value,
            "status": self.status.value,
            "items": [item.to_dict() for item in self.items],
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "total_value": str(self.total_value),
            "requested_by": str(self.requested_by),
            "requested_at": self.requested_at.isoformat(),
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejected_reason": self.rejected_reason,
            "shipped_by": str(self.shipped_by) if self.shipped_by else None,
            "shipped_at": self.shipped_at.isoformat() if self.shipped_at else None,
            "received_by": str(self.received_by) if self.received_by else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "reason": self.reason,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterWarehouseTransferEntity:
        items = []
        for item_data in data.get("items", []):
            items.append(
                TransferItem(
                    item_id=UUID(item_data["item_id"]),
                    item_sku=item_data["item_sku"],
                    item_name=item_data["item_name"],
                    quantity=Decimal(item_data["quantity"]),
                    unit_cost=Decimal(item_data["unit_cost"]),
                    total_value=Decimal(item_data["total_value"]),
                    batch_number=item_data.get("batch_number"),
                    expiry_date=date.fromisoformat(item_data["expiry_date"])
                    if item_data.get("expiry_date")
                    else None,
                )
            )
        return cls(
            transfer_id=UUID(data["transfer_id"]),
            transfer_number=data["transfer_number"],
            source_warehouse_id=UUID(data["source_warehouse_id"]),
            source_warehouse_name=data["source_warehouse_name"],
            destination_warehouse_id=UUID(data["destination_warehouse_id"]),
            destination_warehouse_name=data["destination_warehouse_name"],
            transfer_date=date.fromisoformat(data["transfer_date"]),
            priority=TransferPriority.from_string(data["priority"]),
            status=TransferStatus.from_string(data["status"]),
            items=items,
            requested_by=UUID(data["requested_by"]),
            requested_at=datetime.fromisoformat(data["requested_at"]),
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            rejected_by=UUID(data["rejected_by"]) if data.get("rejected_by") else None,
            rejected_at=datetime.fromisoformat(data["rejected_at"])
            if data.get("rejected_at")
            else None,
            rejected_reason=data.get("rejected_reason"),
            shipped_by=UUID(data["shipped_by"]) if data.get("shipped_by") else None,
            shipped_at=datetime.fromisoformat(data["shipped_at"])
            if data.get("shipped_at")
            else None,
            received_by=UUID(data["received_by"]) if data.get("received_by") else None,
            received_at=datetime.fromisoformat(data["received_at"])
            if data.get("received_at")
            else None,
            completed_by=UUID(data["completed_by"]) if data.get("completed_by") else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            reason=data.get("reason", ""),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=UUID(data["created_by"]),
            version=data.get("version", 1),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
        )


# === 3. ALIAS FOR SERVICE LAYER ===

InterWarehouseTransfer = InterWarehouseTransferEntity


# === 4. REPOSITORY PROTOCOL ===


class InterWarehouseTransferRepository:
    """Repository protocol for InterWarehouseTransferEntity."""

    async def get_by_id(
        self, transfer_id: UUID, legal_entity_id: UUID
    ) -> InterWarehouseTransferEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, transfer_number: str, legal_entity_id: UUID
    ) -> InterWarehouseTransferEntity | None:
        raise NotImplementedError

    async def get_by_source_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        status: TransferStatus | None = None,
    ) -> list[InterWarehouseTransferEntity]:
        raise NotImplementedError

    async def get_by_destination_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        status: TransferStatus | None = None,
    ) -> list[InterWarehouseTransferEntity]:
        raise NotImplementedError

    async def get_pending(self, legal_entity_id: UUID) -> list[InterWarehouseTransferEntity]:
        raise NotImplementedError

    async def save(self, transfer: InterWarehouseTransferEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, transfer_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# === 5. EXPORTS ===

__all__ = [
    "InterWarehouseTransfer",
    "InterWarehouseTransferEntity",
    "InterWarehouseTransferRepository",
    "TransferItem",
    "TransferPriority",
    "TransferStatus",
]
