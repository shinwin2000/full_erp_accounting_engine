#!/usr/bin/env python3
"""
Module: ias_02_inventories.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 2: Inventories.

Dependencies:
- standard library (decimal, datetime, logging, dataclass, enum)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap penilaian persediaan dictat.
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


# === 1. CONSTANTS & ENUMS ===


class IAS2InventoryValuationMethod(Enum):
    FIFO = "fifo"
    WEIGHTED_AVERAGE = "weighted_average"
    SPECIFIC_IDENTIFICATION = "specific_identification"


class IAS2MeasurementBasis(Enum):
    COST = "cost"
    NRV = "nrv"
    LOWER_OF_COST_OR_NRV = "lower_of_cost_or_nrv"


class IAS2CostFormula(Enum):
    SPECIFIC_COST = "specific_cost"
    FIFO = "fifo"
    WEIGHTED_AVERAGE = "weighted_average"


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS2InventoryItem:
    item_id: UUID
    item_code: str
    description: str
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    nrv_per_unit: Decimal
    total_nrv: Decimal
    valuation_basis: IAS2MeasurementBasis
    write_down: Decimal = Decimal(0)

    def __post_init__(self):
        if self.quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if self.unit_cost < 0:
            raise ValueError("Unit cost cannot be negative")
        if self.nrv_per_unit < 0:
            raise ValueError("NRV per unit cannot be negative")

    @property
    def carrying_amount(self) -> Decimal:
        if self.valuation_basis == IAS2MeasurementBasis.LOWER_OF_COST_OR_NRV:
            return min(self.total_cost, self.total_nrv)
        elif self.valuation_basis == IAS2MeasurementBasis.NRV:
            return self.total_nrv
        else:
            return self.total_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "description": self.description,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "total_cost": str(self.total_cost),
            "nrv_per_unit": str(self.nrv_per_unit),
            "total_nrv": str(self.total_nrv),
            "valuation_basis": self.valuation_basis.value,
            "write_down": str(self.write_down),
            "carrying_amount": str(self.carrying_amount),
        }


# === 3. ENTITIES ===


@dataclass
class IAS2Inventory:
    inventory_id: UUID
    entity_id: UUID
    valuation_method: IAS2InventoryValuationMethod
    items: list[IAS2InventoryItem] = field(default_factory=list)
    as_of_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_item(self, item: IAS2InventoryItem) -> IAS2Inventory:
        return IAS2Inventory(
            inventory_id=self.inventory_id,
            entity_id=self.entity_id,
            valuation_method=self.valuation_method,
            items=[*self.items, item],
            as_of_date=self.as_of_date,
        )

    def total_carrying_amount(self) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        return sum((i.carrying_amount for i in self.items), Decimal(0))

    def total_write_down(self) -> Decimal:
        return sum((i.write_down for i in self.items), Decimal(0))

    def total_cost(self) -> Decimal:
        return sum((i.total_cost for i in self.items), Decimal(0))

    def total_nrv(self) -> Decimal:
        return sum((i.total_nrv for i in self.items), Decimal(0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_id": str(self.inventory_id),
            "entity_id": str(self.entity_id),
            "valuation_method": self.valuation_method.value,
            "as_of_date": self.as_of_date.isoformat(),
            "items": [i.to_dict() for i in self.items],
            "total_cost": str(self.total_cost()),
            "total_nrv": str(self.total_nrv()),
            "total_write_down": str(self.total_write_down()),
            "total_carrying": str(self.total_carrying_amount()),
        }


# Alias untuk kompatibilitas dengan __init__.py
IAS2InventoryMeasurement = IAS2Inventory


# === 4. DOMAIN SERVICES ===


class IAS2InventoryService:
    @staticmethod
    def calculate_nrv(
        estimated_selling_price: Decimal,
        estimated_costs_to_complete: Decimal,
        estimated_costs_to_sell: Decimal,
    ) -> Decimal:
        return estimated_selling_price - estimated_costs_to_complete - estimated_costs_to_sell

    @staticmethod
    def calculate_weighted_average_cost(
        purchases: list[tuple[Decimal, Decimal]],
        beginning_inventory_quantity: Decimal,
        beginning_inventory_cost: Decimal,
    ) -> Decimal:
        total_qty = beginning_inventory_quantity
        total_cost = beginning_inventory_cost
        for qty, cost in purchases:
            total_qty += qty
            total_cost += qty * cost
        if total_qty == 0:
            return Decimal(0)
        return total_cost / total_qty

    @staticmethod
    def calculate_fifo_cost(
        outward_quantity: Decimal,
        inventory_layers: list[tuple[Decimal, Decimal]],
    ) -> Decimal:
        remaining = outward_quantity
        cogs = Decimal(0)
        for layer_qty, layer_cost in inventory_layers:
            if remaining <= 0:
                break
            take = min(layer_qty, remaining)
            cogs += take * layer_cost
            remaining -= take
        return cogs

    @staticmethod
    def apply_lcnrv(
        cost: Decimal, nrv: Decimal, existing_allowance: Decimal = Decimal(0)
    ) -> tuple[Decimal, Decimal]:
        if nrv < cost:
            write_down = cost - nrv
            additional = write_down - existing_allowance
            return write_down, max(additional, Decimal(0))
        return Decimal(0), Decimal(0)


# === 5. IAS 2 VALIDATION RESULT ===


@dataclass
class IAS2ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS2ValidationResult) -> IAS2ValidationResult:
        return IAS2ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 6. IAS 2 RULES ===


class IAS2Rules:
    ALLOWED_METHODS: ClassVar[list[IAS2InventoryValuationMethod]] = [
        IAS2InventoryValuationMethod.FIFO,
        IAS2InventoryValuationMethod.WEIGHTED_AVERAGE,
    ]
    DISALLOWED_METHODS: ClassVar[list[str]] = ["lifo"]

    @staticmethod
    def validate_valuation_method(method: IAS2InventoryValuationMethod) -> IAS2ValidationResult:
        result = IAS2ValidationResult(is_compliant=True)
        if method not in IAS2Rules.ALLOWED_METHODS:
            result.add_error(
                f"Valuation method {method.value} not allowed under IAS 2 (LIFO prohibited)"
            )
        return result

    @staticmethod
    def validate_nrv_calculation(
        selling_price: Decimal, costs_to_complete: Decimal, costs_to_sell: Decimal
    ) -> IAS2ValidationResult:
        result = IAS2ValidationResult(is_compliant=True)
        nrv = selling_price - costs_to_complete - costs_to_sell
        if nrv < 0:
            result.add_warning(f"NRV is negative: {nrv}")
        return result


# === 7. IAS 2 VALIDATOR ===


class IAS2Validator:
    def __init__(self):
        self._rules = IAS2Rules()

    def validate_inventory(self, inventory: IAS2Inventory) -> IAS2ValidationResult:
        result = self._rules.validate_valuation_method(inventory.valuation_method)
        for item in inventory.items:
            if item.total_nrv < item.total_cost:
                result.add_warning(
                    f"Item {item.item_code} written down from {item.total_cost} to {item.total_nrv}"
                )
        return result

    def calculate_inventory_value(
        self,
        items: list[dict[str, Any]],
        valuation_method: IAS2InventoryValuationMethod,
        as_of_date: datetime,
    ) -> IAS2Inventory:
        inventory = IAS2Inventory(
            inventory_id=uuid4(),
            entity_id=UUID("00000000-0000-0000-0000-000000000000"),
            valuation_method=valuation_method,
            as_of_date=as_of_date,
        )
        for item_data in items:
            quantity = Decimal(str(item_data.get("quantity", 0)))
            unit_cost = Decimal(str(item_data.get("unit_cost", 0)))
            selling_price = Decimal(str(item_data.get("selling_price", 0)))
            cost_to_sell = Decimal(str(item_data.get("cost_to_sell", 0)))
            cost_to_complete = Decimal(str(item_data.get("cost_to_complete", 0)))

            total_cost = quantity * unit_cost
            nrv_per_unit = IAS2InventoryService.calculate_nrv(
                selling_price, cost_to_complete, cost_to_sell
            )
            total_nrv = quantity * nrv_per_unit

            valuation_basis = IAS2MeasurementBasis.LOWER_OF_COST_OR_NRV
            write_down = Decimal(0)
            if total_nrv < total_cost:
                write_down = total_cost - total_nrv

            inventory_item = IAS2InventoryItem(
                item_id=item_data.get("item_id", uuid4()),
                item_code=item_data.get("item_code", ""),
                description=item_data.get("description", ""),
                quantity=quantity,
                unit_cost=unit_cost,
                total_cost=total_cost,
                nrv_per_unit=nrv_per_unit,
                total_nrv=total_nrv,
                valuation_basis=valuation_basis,
                write_down=write_down,
            )
            inventory = inventory.add_item(inventory_item)
        return inventory

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "measurement": "Lower of cost and net realizable value (LCNRV)",
            "allowed_methods": [m.value for m in self._rules.ALLOWED_METHODS],
            "disallowed_methods": self._rules.DISALLOWED_METHODS,
        }


# === 8. SINGLETON ACCESSOR ===

_ias2_validator_instance: IAS2Validator | None = None


def get_ias2_validator() -> IAS2Validator:
    global _ias2_validator_instance
    if _ias2_validator_instance is None:
        _ias2_validator_instance = IAS2Validator()
    return _ias2_validator_instance


# === 9. EXPORTS ===

__all__ = [
    "IAS2CostFormula",
    "IAS2Inventory",
    "IAS2InventoryItem",
    "IAS2InventoryMeasurement",
    "IAS2InventoryService",
    "IAS2InventoryValuationMethod",
    "IAS2MeasurementBasis",
    "IAS2Rules",
    "IAS2ValidationResult",
    "IAS2Validator",
    "get_ias2_validator",
]
