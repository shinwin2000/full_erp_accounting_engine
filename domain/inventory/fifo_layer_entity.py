#!/usr/bin/env python3
"""
Module: fifo_layer_entity.py
Layer: Domain / Inventory
Responsibility: Define FIFO layer entity for inventory valuation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class FIFOLayer:
    """
    FIFO layer entity representing a purchase batch.

    This is a value object/entity used internally for FIFO cost calculation.
    Audit trail is added for checker compliance.
    """

    id: UUID
    item_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    remaining_quantity: Decimal
    purchase_date: date
    layer_number: int
    batch_code: str | None = None
    location_id: UUID | None = None
    currency: str = "IDR"
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if self.unit_cost < 0:
            raise ValueError("Unit cost cannot be negative")
        if self.remaining_quantity < 0:
            raise ValueError("Remaining quantity cannot be negative")
        if self.remaining_quantity > self.quantity:
            raise ValueError("Remaining quantity cannot exceed original quantity")

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_quantity == 0

    @property
    def total_cost(self) -> Decimal:
        return self.quantity * self.unit_cost

    @property
    def remaining_cost(self) -> Decimal:
        return self.remaining_quantity * self.unit_cost

    def _record_audit(self, action: str, details: dict[str, Any]) -> None:
        """Record audit trail entry for checker compliance."""
        self._audit_trail.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
            "layer_id": str(self.id),
        })

    def consume(self, qty: Decimal) -> Decimal:
        """
        Consume part of this layer, return cost of consumed quantity.
        """
        if qty <= 0:
            raise ValueError("Consumption quantity must be positive")
        if qty > self.remaining_quantity:
            raise ValueError(f"Cannot consume {qty} > remaining {self.remaining_quantity}")
        consumed_cost = qty * self.unit_cost
        self.remaining_quantity -= qty
        # Audit trail for checker compliance (INV-046)
        self._record_audit("consume", {"qty": str(qty), "cost": str(consumed_cost)})
        return consumed_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "remaining_quantity": str(self.remaining_quantity),
            "purchase_date": self.purchase_date.isoformat(),
            "layer_number": self.layer_number,
            "batch_code": self.batch_code,
            "location_id": str(self.location_id) if self.location_id else None,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FIFOLayer:
        return cls(
            id=UUID(data["id"]) if data.get("id") else uuid4(),
            item_id=UUID(data["item_id"]),
            quantity=Decimal(data["quantity"]),
            unit_cost=Decimal(data["unit_cost"]),
            remaining_quantity=Decimal(data["remaining_quantity"]),
            purchase_date=date.fromisoformat(data["purchase_date"]),
            layer_number=data.get("layer_number", 0),
            batch_code=data.get("batch_code"),
            location_id=UUID(data["location_id"]) if data.get("location_id") else None,
            currency=data.get("currency", "IDR"),
        )


__all__ = ["FIFOLayer"]