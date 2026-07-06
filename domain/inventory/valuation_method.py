#!/usr/bin/env python3
"""
Module: valuation_method.py
Layer: 6 - Domain / Inventory
Responsibility: Strategy: FIFO, Average, biaya per batch.

Metode penilaian persediaan yang didukung:
- FIFO (First-In-First-Out)
- LIFO (Last-In-First-Out)
- Weighted Average
- Moving Average
- Specific Identification (per batch)
- Standard Cost

Perbaikan:
- Validasi quantity positif di calculate_cost()
- Docstring lengkap
- Type hints konsisten
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# 1. VALUATION METHOD ENUM
# ============================================================================


class ValuationMethodType(Enum):
    """Tipe metode penilaian persediaan."""

    FIFO = "fifo"
    LIFO = "lifo"
    AVERAGE = "average"
    MOVING_AVERAGE = "moving_average"
    SPECIFIC_ID = "specific_id"
    WEIGHTED_AVERAGE = "weighted_average"
    STANDARD = "standard"

    @classmethod
    def from_string(cls, value: str) -> ValuationMethodType:
        for member in cls:
            if member.value == value.lower() or member.name == value.upper():
                return member
        return cls.FIFO

    def __str__(self) -> str:
        return self.value


ValuationMethod = ValuationMethodType


# ============================================================================
# 2. FIFO LAYER ENTITY (VALUE OBJECT)
# ============================================================================


@dataclass(kw_only=True)
class FIFOLayer:
    """Represents a single FIFO layer (purchase batch)."""

    id: UUID = field(default_factory=uuid4)
    item_id: UUID
    quantity: Decimal
    remaining_quantity: Decimal
    unit_cost: Decimal
    purchase_date: date
    layer_number: int = 0
    batch_code: str | None = None
    location_id: UUID | None = None
    currency: str = "IDR"

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
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

    def consume(self, qty: Decimal) -> Decimal:
        """Consume part of this layer, return cost of consumed quantity."""
        if qty <= 0:
            raise ValueError("Consumption quantity must be positive")
        if qty > self.remaining_quantity:
            raise ValueError(f"Cannot consume {qty} > remaining {self.remaining_quantity}")
        consumed_cost = qty * self.unit_cost
        self.remaining_quantity -= qty
        return consumed_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "quantity": str(self.quantity),
            "remaining_quantity": str(self.remaining_quantity),
            "unit_cost": str(self.unit_cost),
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
            remaining_quantity=Decimal(data["remaining_quantity"]),
            unit_cost=Decimal(data["unit_cost"]),
            purchase_date=date.fromisoformat(data["purchase_date"]),
            layer_number=data.get("layer_number", 0),
            batch_code=data.get("batch_code"),
            location_id=UUID(data["location_id"]) if data.get("location_id") else None,
            currency=data.get("currency", "IDR"),
        )


# ============================================================================
# 3. VALUATION RESULT
# ============================================================================


@dataclass(kw_only=True)
class ValuationResult:
    """Hasil perhitungan nilai persediaan."""

    total_quantity: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)
    unit_cost: Decimal = Decimal(0)
    method: ValuationMethodType = ValuationMethodType.FIFO
    layers: list[dict[str, Any]] = field(default_factory=list)
    cogs: Decimal = Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_quantity": str(self.total_quantity),
            "total_value": str(self.total_value),
            "unit_cost": str(self.unit_cost),
            "method": self.method.value,
            "layers_count": len(self.layers),
            "cogs": str(self.cogs),
        }


# ============================================================================
# 4. VALUATION METHOD STRATEGIES
# ============================================================================


class ValuationMethodStrategy(ABC):
    """Abstract base class for valuation strategies."""

    @abstractmethod
    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        """Calculate current inventory value."""
        pass

    @abstractmethod
    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        """Calculate Cost of Goods Sold."""
        pass

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """
        Calculate the cost for a given quantity using the valuation method.
        Default implementation uses FIFO.
        """
        if quantity <= 0:
            return Decimal(0)
        return FIFOValuation.calculate_cost_static(layers, quantity)


class FIFOValuation(ValuationMethodStrategy):
    """First-In-First-Out valuation method."""

    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        """Calculate inventory value using FIFO."""
        layers = []
        remaining_quantity = Decimal(0)
        total_value = Decimal(0)

        inbound = [m for m in movements if getattr(m, "is_inbound", lambda: False)()]
        inbound.sort(key=lambda m: m.movement_date)

        for movement in inbound:
            layers.append({
                "quantity": movement.quantity,
                "unit_cost": movement.unit_cost,
                "total_value": movement.total_cost,
                "date": movement.movement_date,
            })
            remaining_quantity += movement.quantity
            total_value += movement.total_cost

        outbound = [m for m in movements if getattr(m, "is_outbound", lambda: False)()]
        for outward in outbound:
            remaining = outward.quantity
            for layer in layers:
                if remaining <= 0:
                    break
                if layer["quantity"] > 0:
                    deduct = min(layer["quantity"], remaining)
                    layer["quantity"] -= deduct
                    remaining -= deduct
                    total_value -= deduct * layer["unit_cost"]
                    remaining_quantity -= deduct

        active_layers = [l for l in layers if l["quantity"] > 0]
        unit_cost = total_value / remaining_quantity if remaining_quantity > 0 else Decimal(0)
        unit_cost = unit_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return ValuationResult(
            total_quantity=remaining_quantity.quantize(Decimal("0.001")),
            total_value=total_value.quantize(Decimal("0.01")),
            unit_cost=unit_cost,
            method=ValuationMethodType.FIFO,
            layers=active_layers,
        )

    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        """Calculate COGS using FIFO."""
        cogs = Decimal(0)
        fifo_layers = []

        for movement in sorted(inward_movements, key=lambda m: m.movement_date):
            fifo_layers.append({
                "quantity": movement.quantity,
                "unit_cost": movement.unit_cost,
            })

        for outward in sorted(outward_movements, key=lambda m: m.movement_date):
            remaining = outward.quantity
            for layer in fifo_layers:
                if remaining <= 0:
                    break
                if layer["quantity"] > 0:
                    deduct = min(layer["quantity"], remaining)
                    cogs += deduct * layer["unit_cost"]
                    layer["quantity"] -= deduct
                    remaining -= deduct

        return cogs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """
        Calculate total cost for a given quantity using FIFO layers.
        Validates quantity > 0.
        """
        if quantity <= 0:
            return Decimal(0)
        return FIFOValuation.calculate_cost_static(layers, quantity)

    # ========================================================================
    # Static helper methods
    # ========================================================================

    @staticmethod
    def calculate_cost_static(layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """
        Calculate total cost for a given quantity using FIFO layers.
        Works with both dict layers and FIFOLayer objects.
        """
        if quantity <= 0:
            return Decimal(0)

        remaining = quantity
        total_cost = Decimal(0)

        # Convert to uniform format
        layer_list = []
        for layer in layers:
            if isinstance(layer, FIFOLayer):
                qty = layer.remaining_quantity
                unit_cost = layer.unit_cost
            else:
                qty = layer.get("remaining_quantity", layer.get("quantity", 0))
                unit_cost = layer["unit_cost"]
            if qty > 0:
                layer_list.append({"quantity": qty, "unit_cost": unit_cost})

        for layer in layer_list:
            if remaining <= 0:
                break
            if layer["quantity"] > 0:
                consume = min(layer["quantity"], remaining)
                total_cost += consume * layer["unit_cost"]
                layer["quantity"] -= consume
                remaining -= consume

        if remaining > 0:
            raise ValueError(f"Not enough inventory to cover {quantity} units")

        return total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def consume(layers: list[FIFOLayer], quantity: Decimal) -> tuple[Decimal, list[FIFOLayer]]:
        """Consume inventory using FIFO. Returns (total_cost_consumed, updated_layers)."""
        if quantity < 0:
            raise ValueError("Quantity to consume cannot be negative")
        if quantity == 0:
            return Decimal(0), layers[:]

        total_available = sum(l.remaining_quantity for l in layers)
        if quantity > total_available:
            raise ValueError(
                f"Quantity {quantity} exceeds available quantity (available: {total_available})"
            )

        remaining_qty = quantity
        total_cost = Decimal(0)
        new_layers = [
            FIFOLayer(
                id=l.id,
                item_id=l.item_id,
                quantity=l.quantity,
                remaining_quantity=l.remaining_quantity,
                unit_cost=l.unit_cost,
                purchase_date=l.purchase_date,
                layer_number=l.layer_number,
                batch_code=l.batch_code,
                location_id=l.location_id,
                currency=l.currency,
            )
            for l in layers
        ]

        for layer in new_layers:
            if remaining_qty <= 0:
                break
            if layer.remaining_quantity <= remaining_qty:
                total_cost += layer.remaining_quantity * layer.unit_cost
                remaining_qty -= layer.remaining_quantity
                layer.remaining_quantity = Decimal(0)
            else:
                total_cost += remaining_qty * layer.unit_cost
                layer.remaining_quantity -= remaining_qty
                remaining_qty = Decimal(0)

        return total_cost.quantize(Decimal("0.01")), new_layers

    @staticmethod
    def add_layer(layers: list[FIFOLayer], new_layer: FIFOLayer) -> list[FIFOLayer]:
        """Add a new layer and return sorted list."""
        if new_layer.quantity <= 0:
            raise ValueError("New layer quantity must be positive")
        new_layers = layers + [new_layer]
        return FIFOValuation.sort_layers_by_date(new_layers)

    @staticmethod
    def get_current_cost(layers: list[FIFOLayer]) -> Decimal:
        """Get the cost of the oldest layer (current cost for FIFO)."""
        if not layers:
            return Decimal(0)
        sorted_layers = FIFOValuation.sort_layers_by_date(layers)
        return sorted_layers[0].unit_cost

    @staticmethod
    def get_remaining_value(layers: list[FIFOLayer]) -> Decimal:
        """Get total remaining value of all layers."""
        return sum(l.remaining_quantity * l.unit_cost for l in layers).quantize(Decimal("0.01"))

    @staticmethod
    def sort_layers_by_date(layers: list[FIFOLayer]) -> list[FIFOLayer]:
        """Sort layers by purchase date then layer number."""
        return sorted(layers, key=lambda l: (l.purchase_date, l.layer_number))

    @staticmethod
    def remove_empty_layers(layers: list[FIFOLayer]) -> list[FIFOLayer]:
        """Remove layers with remaining_quantity <= 0."""
        return [l for l in layers if l.remaining_quantity > 0]


class LIFOValuation(ValuationMethodStrategy):
    """Last-In-First-Out valuation method."""

    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        layers = []
        remaining_quantity = Decimal(0)
        total_value = Decimal(0)

        inbound = [m for m in movements if getattr(m, "is_inbound", lambda: False)()]
        inbound.sort(key=lambda m: m.movement_date)

        for movement in inbound:
            layers.append({
                "quantity": movement.quantity,
                "unit_cost": movement.unit_cost,
                "total_value": movement.total_cost,
                "date": movement.movement_date,
            })
            remaining_quantity += movement.quantity
            total_value += movement.total_cost

        outbound = [m for m in movements if getattr(m, "is_outbound", lambda: False)()]
        for outward in outbound:
            remaining = outward.quantity
            for layer in reversed(layers):
                if remaining <= 0:
                    break
                if layer["quantity"] > 0:
                    deduct = min(layer["quantity"], remaining)
                    layer["quantity"] -= deduct
                    remaining -= deduct
                    total_value -= deduct * layer["unit_cost"]
                    remaining_quantity -= deduct

        active_layers = [l for l in layers if l["quantity"] > 0]
        unit_cost = total_value / remaining_quantity if remaining_quantity > 0 else Decimal(0)
        unit_cost = unit_cost.quantize(Decimal("0.01"))

        return ValuationResult(
            total_quantity=remaining_quantity.quantize(Decimal("0.001")),
            total_value=total_value.quantize(Decimal("0.01")),
            unit_cost=unit_cost,
            method=ValuationMethodType.LIFO,
            layers=active_layers,
        )

    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        cogs = Decimal(0)
        lifo_layers = []

        for movement in sorted(inward_movements, key=lambda m: m.movement_date):
            lifo_layers.append({
                "quantity": movement.quantity,
                "unit_cost": movement.unit_cost,
            })

        for outward in sorted(outward_movements, key=lambda m: m.movement_date):
            remaining = outward.quantity
            for layer in reversed(lifo_layers):
                if remaining <= 0:
                    break
                if layer["quantity"] > 0:
                    deduct = min(layer["quantity"], remaining)
                    cogs += deduct * layer["unit_cost"]
                    layer["quantity"] -= deduct
                    remaining -= deduct

        return cogs.quantize(Decimal("0.01"))

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """Calculate cost using LIFO (consume from newest layers first)."""
        if quantity <= 0:
            return Decimal(0)

        remaining = quantity
        total_cost = Decimal(0)

        # Convert to uniform format
        layer_list = []
        for layer in layers:
            if isinstance(layer, FIFOLayer):
                qty = layer.remaining_quantity
                unit_cost = layer.unit_cost
            else:
                qty = layer.get("remaining_quantity", layer.get("quantity", 0))
                unit_cost = layer["unit_cost"]
            if qty > 0:
                layer_list.append({"quantity": qty, "unit_cost": unit_cost})

        # Process from newest to oldest (reverse order)
        for layer in reversed(layer_list):
            if remaining <= 0:
                break
            if layer["quantity"] > 0:
                consume = min(layer["quantity"], remaining)
                total_cost += consume * layer["unit_cost"]
                layer["quantity"] -= consume
                remaining -= consume

        if remaining > 0:
            raise ValueError(f"Not enough inventory to cover {quantity} units")

        return total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class AverageValuation(ValuationMethodStrategy):
    """Weighted Average valuation method."""

    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        total_quantity = Decimal(0)
        total_value = Decimal(0)
        sorted_movements = sorted(movements, key=lambda m: m.movement_date)

        for movement in sorted_movements:
            if movement.is_inbound():
                total_quantity += movement.quantity
                total_value += movement.total_cost
            else:
                avg_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
                cogs = movement.quantity * avg_cost
                total_quantity -= movement.quantity
                total_value -= cogs

        unit_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
        unit_cost = unit_cost.quantize(Decimal("0.01"))

        return ValuationResult(
            total_quantity=total_quantity.quantize(Decimal("0.001")),
            total_value=total_value.quantize(Decimal("0.01")),
            unit_cost=unit_cost,
            method=ValuationMethodType.AVERAGE,
        )

    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        total_quantity = Decimal(0)
        total_value = Decimal(0)
        cogs = Decimal(0)
        all_movements = sorted(inward_movements + outward_movements, key=lambda m: m.movement_date)

        for movement in all_movements:
            if movement.is_inbound():
                total_quantity += movement.quantity
                total_value += movement.total_cost
            else:
                avg_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
                cogs += movement.quantity * avg_cost
                total_quantity -= movement.quantity
                total_value -= movement.quantity * avg_cost

        return cogs.quantize(Decimal("0.01"))

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """Calculate cost using weighted average."""
        if quantity <= 0:
            return Decimal(0)

        total_qty = Decimal(0)
        total_value = Decimal(0)

        for layer in layers:
            if isinstance(layer, FIFOLayer):
                qty = layer.remaining_quantity
                unit_cost = layer.unit_cost
            else:
                qty = layer.get("remaining_quantity", layer.get("quantity", 0))
                unit_cost = layer["unit_cost"]
            total_qty += qty
            total_value += qty * unit_cost

        if total_qty <= 0:
            raise ValueError("No inventory available")

        avg_cost = total_value / total_qty
        return (quantity * avg_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class WeightedAverageValuation(AverageValuation):
    """Alias for AverageValuation."""
    pass


class MovingAverageValuation(ValuationMethodStrategy):
    """Moving Average valuation method."""

    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        total_quantity = Decimal(0)
        total_value = Decimal(0)
        sorted_movements = sorted(movements, key=lambda m: m.movement_date)

        for movement in sorted_movements:
            if movement.is_inbound():
                total_quantity += movement.quantity
                total_value += movement.total_cost
            else:
                avg_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
                cogs = movement.quantity * avg_cost
                total_quantity -= movement.quantity
                total_value -= cogs

        unit_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
        unit_cost = unit_cost.quantize(Decimal("0.01"))

        return ValuationResult(
            total_quantity=total_quantity.quantize(Decimal("0.001")),
            total_value=total_value.quantize(Decimal("0.01")),
            unit_cost=unit_cost,
            method=ValuationMethodType.MOVING_AVERAGE,
        )

    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        total_quantity = Decimal(0)
        total_value = Decimal(0)
        cogs = Decimal(0)
        all_movements = sorted(inward_movements + outward_movements, key=lambda m: m.movement_date)

        for movement in all_movements:
            if movement.is_inbound():
                total_quantity += movement.quantity
                total_value += movement.total_cost
            else:
                avg_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
                cogs += movement.quantity * avg_cost
                total_quantity -= movement.quantity
                total_value -= movement.quantity * avg_cost

        return cogs.quantize(Decimal("0.01"))

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """Calculate cost using moving average."""
        if quantity <= 0:
            return Decimal(0)

        total_qty = Decimal(0)
        total_value = Decimal(0)

        for layer in layers:
            if isinstance(layer, FIFOLayer):
                qty = layer.remaining_quantity
                unit_cost = layer.unit_cost
            else:
                qty = layer.get("remaining_quantity", layer.get("quantity", 0))
                unit_cost = layer["unit_cost"]
            total_qty += qty
            total_value += qty * unit_cost

        if total_qty <= 0:
            raise ValueError("No inventory available")

        avg_cost = total_value / total_qty
        return (quantity * avg_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class SpecificIdentificationValuation(ValuationMethodStrategy):
    """Specific identification valuation method (by batch)."""

    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        batch_inventory: dict[str, dict] = {}
        total_quantity = Decimal(0)
        total_value = Decimal(0)

        for movement in movements:
            batch_key = movement.batch_number or str(movement.movement_id)
            if movement.is_inbound():
                batch_inventory[batch_key] = {
                    "quantity": movement.quantity,
                    "unit_cost": movement.unit_cost,
                    "total_value": movement.total_cost,
                    "batch_number": movement.batch_number,
                }
                total_quantity += movement.quantity
                total_value += movement.total_cost
            else:
                if movement.batch_number and movement.batch_number in batch_inventory:
                    batch = batch_inventory[movement.batch_number]
                    deduct = min(batch["quantity"], movement.quantity)
                    batch["quantity"] -= deduct
                    total_quantity -= deduct
                    total_value -= deduct * batch["unit_cost"]

        active_batches = [b for b in batch_inventory.values() if b["quantity"] > 0]
        unit_cost = total_value / total_quantity if total_quantity > 0 else Decimal(0)
        unit_cost = unit_cost.quantize(Decimal("0.01"))

        return ValuationResult(
            total_quantity=total_quantity.quantize(Decimal("0.001")),
            total_value=total_value.quantize(Decimal("0.01")),
            unit_cost=unit_cost,
            method=ValuationMethodType.SPECIFIC_ID,
            layers=active_batches,
        )

    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        cogs = Decimal(0)
        inbound_by_batch = {m.batch_number: m for m in inward_movements if m.batch_number}
        for outward in outward_movements:
            if outward.batch_number and outward.batch_number in inbound_by_batch:
                inbound = inbound_by_batch[outward.batch_number]
                cogs += outward.quantity * inbound.unit_cost
            else:
                avg_cost = (
                    sum(m.unit_cost for m in inward_movements) / len(inward_movements)
                    if inward_movements
                    else Decimal(0)
                )
                cogs += outward.quantity * avg_cost
        return cogs.quantize(Decimal("0.01"))

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """Calculate cost using specific identification (by batch)."""
        if quantity <= 0:
            return Decimal(0)

        total_cost = Decimal(0)
        remaining = quantity

        for layer in layers:
            if remaining <= 0:
                break
            if isinstance(layer, FIFOLayer):
                qty = layer.remaining_quantity
                unit_cost = layer.unit_cost
            else:
                qty = layer.get("remaining_quantity", layer.get("quantity", 0))
                unit_cost = layer["unit_cost"]
            if qty > 0:
                consume = min(qty, remaining)
                total_cost += consume * unit_cost
                remaining -= consume

        if remaining > 0:
            raise ValueError(f"Not enough inventory to cover {quantity} units")

        return total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class StandardCostValuation(ValuationMethodStrategy):
    """Standard cost valuation method."""

    def __init__(self, standard_cost: Decimal | None = None):
        self._standard_cost = standard_cost or Decimal(0)

    def calculate_value(
        self,
        movements: list[Any],
        current_unit_cost: Decimal | None = None,
    ) -> ValuationResult:
        std_cost = current_unit_cost or self._standard_cost
        if std_cost <= 0:
            raise ValueError("Standard cost must be provided and greater than 0")

        total_quantity = Decimal(0)
        for movement in movements:
            if movement.is_inbound():
                total_quantity += movement.quantity
            else:
                total_quantity -= movement.quantity

        total_value = total_quantity * std_cost
        return ValuationResult(
            total_quantity=total_quantity.quantize(Decimal("0.001")),
            total_value=total_value.quantize(Decimal("0.01")),
            unit_cost=std_cost.quantize(Decimal("0.01")),
            method=ValuationMethodType.STANDARD,
        )

    def calculate_cogs(
        self,
        outward_movements: list[Any],
        inward_movements: list[Any],
    ) -> Decimal:
        # Standard cost COGS: sum of outward quantities * standard cost
        std_cost = self._standard_cost
        if std_cost <= 0 and inward_movements:
            total_cost = sum(m.total_cost for m in inward_movements)
            total_qty = sum(m.quantity for m in inward_movements)
            std_cost = total_cost / total_qty if total_qty > 0 else Decimal(0)

        if std_cost <= 0:
            return Decimal(0)

        cogs = sum(m.quantity for m in outward_movements) * std_cost
        return cogs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_cost(self, layers: list[dict] | list[FIFOLayer], quantity: Decimal) -> Decimal:
        """Calculate cost using standard cost."""
        if quantity <= 0:
            return Decimal(0)
        std_cost = self._standard_cost
        if std_cost <= 0:
            # Try to derive from layers
            if layers:
                total_qty = Decimal(0)
                total_val = Decimal(0)
                for layer in layers:
                    if isinstance(layer, FIFOLayer):
                        qty = layer.remaining_quantity
                        unit_cost = layer.unit_cost
                    else:
                        qty = layer.get("remaining_quantity", layer.get("quantity", 0))
                        unit_cost = layer["unit_cost"]
                    total_qty += qty
                    total_val += qty * unit_cost
                if total_qty > 0:
                    std_cost = total_val / total_qty
            if std_cost <= 0:
                raise ValueError("Standard cost not available")
        return (quantity * std_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ============================================================================
# 5. VALUATION METHOD FACTORY
# ============================================================================


class ValuationMethodFactory:
    """Factory to get the appropriate valuation strategy."""

    @staticmethod
    def get_method(method_type: ValuationMethodType, standard_cost: Decimal | None = None) -> ValuationMethodStrategy:
        if method_type == ValuationMethodType.FIFO:
            return FIFOValuation()
        elif method_type == ValuationMethodType.LIFO:
            return LIFOValuation()
        elif method_type in (ValuationMethodType.AVERAGE, ValuationMethodType.WEIGHTED_AVERAGE):
            return WeightedAverageValuation()
        elif method_type == ValuationMethodType.MOVING_AVERAGE:
            return MovingAverageValuation()
        elif method_type == ValuationMethodType.SPECIFIC_ID:
            return SpecificIdentificationValuation()
        elif method_type == ValuationMethodType.STANDARD:
            return StandardCostValuation(standard_cost)
        else:
            return FIFOValuation()

    @staticmethod
    def get_method_by_name(name: str, standard_cost: Decimal | None = None) -> ValuationMethodStrategy:
        method_type = ValuationMethodType.from_string(name)
        return ValuationMethodFactory.get_method(method_type, standard_cost)


# ============================================================================
# 6. SIMPLE FIFO VALUATION FOR TESTING (FifoValuation class)
# ============================================================================


class FifoValuation:
    """Simple FIFO valuation for testing purposes."""

    def __init__(self, transactions: list[tuple]):
        """
        transactions: list of (date, quantity, unit_cost)
        """
        self.transactions = transactions
        self._inbound = []
        for t in transactions:
            if len(t) == 3:
                self._inbound.append({"quantity": t[1], "unit_cost": t[2], "date": t[0]})
        self._inbound.sort(key=lambda x: x["date"])
        self._last_consumed_quantity = Decimal(0)

    def calculate_cogs(self, quantity: Decimal) -> Decimal:
        remaining = quantity
        cogs = Decimal(0)
        layers = [layer.copy() for layer in self._inbound]
        for layer in layers:
            if remaining <= 0:
                break
            if layer["quantity"] > 0:
                consume = min(layer["quantity"], remaining)
                cogs += consume * layer["unit_cost"]
                layer["quantity"] -= consume
                remaining -= consume
        if remaining > 0:
            raise ValueError(f"Not enough inventory to fulfill {quantity}")
        self._last_consumed_quantity = quantity
        self._layers = layers
        return cogs

    def get_remaining(self):
        """Return remaining quantity and value after last consumption."""
        if not hasattr(self, "_layers"):
            total_qty = sum(l["quantity"] for l in self._inbound)
            total_val = sum(l["quantity"] * l["unit_cost"] for l in self._inbound)
            return type("Remaining", (), {"quantity": total_qty, "value": total_val})()
        remaining_qty = Decimal(0)
        remaining_value = Decimal(0)
        for layer in self._layers:
            if layer["quantity"] > 0:
                remaining_qty += layer["quantity"]
                remaining_value += layer["quantity"] * layer["unit_cost"]
        return type("Remaining", (), {"quantity": remaining_qty, "value": remaining_value})()


# ============================================================================
# 7. HELPER FUNCTIONS
# ============================================================================


def get_valuation_method(method_name: str) -> ValuationMethodType:
    """Get ValuationMethodType from string."""
    try:
        return ValuationMethodType[method_name.upper()]
    except KeyError:
        return ValuationMethodType.FIFO


# ============================================================================
# 8. EXPORTS
# ============================================================================

__all__ = [
    "AverageValuation",
    "FIFOLayer",
    "FIFOValuation",
    "FifoValuation",
    "LIFOValuation",
    "MovingAverageValuation",
    "SpecificIdentificationValuation",
    "StandardCostValuation",
    "ValuationMethod",
    "ValuationMethodFactory",
    "ValuationMethodStrategy",
    "ValuationMethodType",
    "ValuationResult",
    "WeightedAverageValuation",
    "get_valuation_method",
]