#!/usr/bin/env python3
"""
Module: cost_card_entity.py
Layer: 6 - Domain / Manufacturing
Responsibility: Production cost card per work order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.cost_element_enum import CostElement

logger = logging.getLogger(__name__)


class CostCardStatus(Enum):
    """Cost card status."""

    OPEN = "open"
    CLOSED = "closed"
    ADJUSTED = "adjusted"

    @classmethod
    def from_string(cls, value: str) -> CostCardStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.OPEN


@dataclass(frozen=True)
class CostEntry:
    """
    Individual cost entry within a cost card (immutable value object).

    Attributes:
        entry_id: Unique identifier.
        cost_element: Type of cost (material, labor, overhead).
        amount: Cost amount.
        quantity: Quantity of the cost driver.
        unit_cost: Cost per unit of quantity.
        transaction_date: Date when the cost was incurred.
        reference_type: Type of reference document.
        reference_id: ID of the reference document.
        reference_number: Human-readable reference number.
        description: Optional description.
        created_by: User who created this entry.
        created_at: Creation timestamp.
    """

    entry_id: UUID
    cost_element: CostElement
    amount: Decimal
    quantity: Decimal
    unit_cost: Decimal
    transaction_date: datetime
    reference_type: str
    reference_id: UUID
    reference_number: str
    description: str = ""
    created_by: str = "system"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.quantity}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")
        if self.transaction_date.tzinfo is None:
            raise ValueError("transaction_date must be timezone-aware")
        if not self.reference_type or len(self.reference_type.strip()) < 2:
            raise ValueError("reference_type cannot be empty")
        if not self.reference_number or len(self.reference_number.strip()) < 1:
            raise ValueError("reference_number cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "cost_element": self.cost_element.value,
            "amount": str(self.amount),
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "transaction_date": self.transaction_date.isoformat(),
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id),
            "reference_number": self.reference_number,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostEntry:
        return cls(
            entry_id=UUID(data["entry_id"]),
            cost_element=CostElement.from_string(data["cost_element"]),
            amount=Decimal(data["amount"]),
            quantity=Decimal(data["quantity"]),
            unit_cost=Decimal(data["unit_cost"]),
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            reference_type=data["reference_type"],
            reference_id=UUID(data["reference_id"]),
            reference_number=data["reference_number"],
            description=data.get("description", ""),
            created_by=data.get("created_by", "system"),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
        )


@dataclass
class CostCardEntity:
    """
    Cost card entity for a work order.

    Business context:
    Records all costs incurred for a work order, including raw materials,
    labor, and overhead. Used for cost tracking and final HPP calculation.
    """

    cost_card_id: UUID
    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str
    product_name: str
    planned_quantity: Decimal
    completed_quantity: Decimal
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    status: CostCardStatus
    entries: list[CostEntry] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.planned_quantity <= 0:
            raise ValueError(f"Planned quantity must be positive: {self.planned_quantity}")
        if self.completed_quantity < 0:
            raise ValueError("Completed quantity cannot be negative")
        if self.completed_quantity > self.planned_quantity:
            raise ValueError(
                f"Completed quantity {self.completed_quantity} exceeds planned {self.planned_quantity}"
            )
        if self.material_cost < 0 or self.labor_cost < 0 or self.overhead_cost < 0:
            raise ValueError("Cost components cannot be negative")
        calc_total = self.material_cost + self.labor_cost + self.overhead_cost
        if abs(self.total_cost - calc_total) > Decimal("0.01"):
            raise ValueError(
                f"Total cost mismatch: {self.total_cost} vs sum of components {calc_total}"
            )
        if self.completed_quantity > 0:
            expected_unit = self.total_cost / self.completed_quantity
            if abs(self.unit_cost - expected_unit) > Decimal("0.01"):
                raise ValueError(f"Unit cost mismatch: {self.unit_cost} vs {expected_unit}")
        else:
            if self.unit_cost != Decimal(0):
                raise ValueError("Unit cost must be zero when no units completed")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, user_id: str, details: dict | None = None) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    # ==================== FACTORY METHOD ====================

    @classmethod
    def create(
        cls,
        work_order_id: UUID,
        work_order_number: str,
        product_id: UUID,
        product_code: str,
        product_name: str,
        planned_quantity: Decimal,
        created_by: str = "system",
    ) -> CostCardEntity:
        if planned_quantity <= 0:
            raise ValueError(f"Planned quantity must be positive: {planned_quantity}")
        instance = cls(
            cost_card_id=uuid4(),
            work_order_id=work_order_id,
            work_order_number=work_order_number,
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            planned_quantity=planned_quantity,
            completed_quantity=Decimal(0),
            material_cost=Decimal(0),
            labor_cost=Decimal(0),
            overhead_cost=Decimal(0),
            total_cost=Decimal(0),
            unit_cost=Decimal(0),
            status=CostCardStatus.OPEN,
            created_by=created_by,
        )
        instance._record_audit("created", created_by, {"work_order_number": work_order_number})
        return instance

    # ==================== COST ADDITION METHODS ====================

    def _add_cost_entry(
        self,
        cost_element: CostElement,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        transaction_date: datetime,
        reference_type: str,
        reference_id: UUID,
        reference_number: str,
        description: str,
        added_by: str,
    ) -> CostCardEntity:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if unit_cost < 0:
            raise ValueError("Unit cost cannot be negative")

        entry = CostEntry(
            entry_id=uuid4(),
            cost_element=cost_element,
            amount=amount,
            quantity=quantity,
            unit_cost=unit_cost,
            transaction_date=transaction_date,
            reference_type=reference_type,
            reference_id=reference_id,
            reference_number=reference_number,
            description=description,
            created_by=added_by,
        )

        new_entries = [*self.entries, entry]

        if cost_element == CostElement.MATERIAL:
            new_material = self.material_cost + amount
            new_labor = self.labor_cost
            new_overhead = self.overhead_cost
        elif cost_element == CostElement.LABOR:
            new_material = self.material_cost
            new_labor = self.labor_cost + amount
            new_overhead = self.overhead_cost
        elif cost_element == CostElement.OVERHEAD:
            new_material = self.material_cost
            new_labor = self.labor_cost
            new_overhead = self.overhead_cost + amount
        else:
            new_material = self.material_cost
            new_labor = self.labor_cost
            new_overhead = self.overhead_cost + amount

        new_total = new_material + new_labor + new_overhead
        new_unit = (
            new_total / self.completed_quantity if self.completed_quantity > 0 else Decimal(0)
        )

        self._record_audit(
            "cost_added",
            added_by,
            {
                "cost_element": cost_element.value,
                "amount": str(amount),
                "reference_number": reference_number,
            },
        )

        return CostCardEntity(
            cost_card_id=self.cost_card_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            material_cost=new_material,
            labor_cost=new_labor,
            overhead_cost=new_overhead,
            total_cost=new_total,
            unit_cost=new_unit,
            status=self.status,
            entries=new_entries,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def add_material_cost(
        self,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        transaction_date: datetime,
        reference_type: str,
        reference_id: UUID,
        reference_number: str,
        description: str = "",
        added_by: str = "system",
    ) -> CostCardEntity:
        return self._add_cost_entry(
            CostElement.MATERIAL,
            amount,
            quantity,
            unit_cost,
            transaction_date,
            reference_type,
            reference_id,
            reference_number,
            description,
            added_by,
        )

    def add_labor_cost(
        self,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        transaction_date: datetime,
        reference_type: str,
        reference_id: UUID,
        reference_number: str,
        description: str = "",
        added_by: str = "system",
    ) -> CostCardEntity:
        return self._add_cost_entry(
            CostElement.LABOR,
            amount,
            quantity,
            unit_cost,
            transaction_date,
            reference_type,
            reference_id,
            reference_number,
            description,
            added_by,
        )

    def add_overhead_cost(
        self,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        transaction_date: datetime,
        reference_type: str,
        reference_id: UUID,
        reference_number: str,
        description: str = "",
        added_by: str = "system",
    ) -> CostCardEntity:
        return self._add_cost_entry(
            CostElement.OVERHEAD,
            amount,
            quantity,
            unit_cost,
            transaction_date,
            reference_type,
            reference_id,
            reference_number,
            description,
            added_by,
        )

    # ==================== COMPLETION METHOD ====================

    def complete_units(self, completed_quantity: Decimal, completed_by: str) -> CostCardEntity:
        if completed_quantity <= 0:
            raise ValueError("Completed quantity must be positive")
        new_completed = self.completed_quantity + completed_quantity
        if new_completed > self.planned_quantity:
            raise ValueError(
                f"Cannot complete {completed_quantity} units, only {self.planned_quantity - self.completed_quantity} remaining"
            )
        new_unit = self.total_cost / new_completed if new_completed > 0 else Decimal(0)
        new_status = (
            CostCardStatus.CLOSED if new_completed >= self.planned_quantity else self.status
        )

        self._record_audit(
            "units_completed",
            completed_by,
            {
                "completed_quantity": str(completed_quantity),
                "total_completed": str(new_completed),
                "unit_cost": str(new_unit),
            },
        )

        return CostCardEntity(
            cost_card_id=self.cost_card_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            planned_quantity=self.planned_quantity,
            completed_quantity=new_completed,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=self.total_cost,
            unit_cost=new_unit,
            status=new_status,
            entries=self.entries,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=completed_by,
            version=self.version + 1,
        )

    # ==================== ADJUSTMENT METHOD ====================

    def adjust_cost(self, new_total_cost: Decimal, reason: str, adjusted_by: str) -> CostCardEntity:
        if new_total_cost < 0:
            raise ValueError("Total cost cannot be negative")

        if self.total_cost > 0:
            ratio = new_total_cost / self.total_cost
            new_material = (self.material_cost * ratio).quantize(Decimal("0.01"))
            new_labor = (self.labor_cost * ratio).quantize(Decimal("0.01"))
            new_overhead = (self.overhead_cost * ratio).quantize(Decimal("0.01"))
        else:
            new_material = Decimal(0)
            new_labor = Decimal(0)
            new_overhead = Decimal(0)

        adjustment_entry = CostEntry(
            entry_id=uuid4(),
            cost_element=CostElement.OTHER,
            amount=new_total_cost - self.total_cost,
            quantity=Decimal(0),
            unit_cost=Decimal(0),
            transaction_date=datetime.now(UTC),
            reference_type="adjustment",
            reference_id=self.cost_card_id,
            reference_number=reason[:50] if reason else "cost_adjustment",
            description=f"Cost adjustment: {reason}",
            created_by=adjusted_by,
        )
        new_entries = [*self.entries, adjustment_entry]

        new_unit = (
            new_total_cost / self.completed_quantity if self.completed_quantity > 0 else Decimal(0)
        )

        self._record_audit(
            "cost_adjusted",
            adjusted_by,
            {
                "old_total_cost": str(self.total_cost),
                "new_total_cost": str(new_total_cost),
                "reason": reason,
            },
        )

        return CostCardEntity(
            cost_card_id=self.cost_card_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            material_cost=new_material,
            labor_cost=new_labor,
            overhead_cost=new_overhead,
            total_cost=new_total_cost,
            unit_cost=new_unit,
            status=CostCardStatus.ADJUSTED,
            entries=new_entries,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=adjusted_by,
            version=self.version + 1,
        )

    # ==================== VALIDATION ====================

    def validate(self) -> list[str]:
        errors = []
        if self.planned_quantity <= 0:
            errors.append("Planned quantity must be positive")
        if self.completed_quantity < 0:
            errors.append("Completed quantity cannot be negative")
        if self.completed_quantity > self.planned_quantity:
            errors.append(
                f"Completed quantity {self.completed_quantity} exceeds planned {self.planned_quantity}"
            )
        calc_total = self.material_cost + self.labor_cost + self.overhead_cost
        if abs(self.total_cost - calc_total) > Decimal("0.01"):
            errors.append(f"Total cost mismatch: {self.total_cost} vs {calc_total}")
        return errors

    # ==================== CLONE ====================

    def clone(self) -> CostCardEntity:
        self._record_audit("cloned", "system", {"source_id": str(self.cost_card_id)})
        return CostCardEntity(
            cost_card_id=uuid4(),
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=self.total_cost,
            unit_cost=self.unit_cost,
            status=self.status,
            entries=self.entries.copy(),
            created_by=self.created_by,
            version=1,
        )

    # ==================== QUERY METHODS ====================

    def get_remaining_quantity(self) -> Decimal:
        return self.planned_quantity - self.completed_quantity

    def get_completion_percentage(self) -> float:
        if self.planned_quantity == 0:
            return 0.0
        return float(self.completed_quantity / self.planned_quantity * 100)

    def get_summary(self) -> dict[str, Any]:
        return {
            "total_entries": len(self.entries),
            "material_cost": str(self.material_cost),
            "labor_cost": str(self.labor_cost),
            "overhead_cost": str(self.overhead_cost),
            "total_cost": str(self.total_cost),
            "unit_cost": str(self.unit_cost),
            "completion_rate": self.get_completion_percentage(),
            "remaining_quantity": str(self.get_remaining_quantity()),
        }

    # ==================== DICTIONARY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_card_id": str(self.cost_card_id),
            "work_order_id": str(self.work_order_id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "planned_quantity": str(self.planned_quantity),
            "completed_quantity": str(self.completed_quantity),
            "remaining_quantity": str(self.get_remaining_quantity()),
            "completion_percentage": self.get_completion_percentage(),
            "material_cost": str(self.material_cost),
            "labor_cost": str(self.labor_cost),
            "overhead_cost": str(self.overhead_cost),
            "total_cost": str(self.total_cost),
            "unit_cost": str(self.unit_cost),
            "status": self.status.value,
            "entries": [e.to_dict() for e in self.entries],
            "summary": self.get_summary(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostCardEntity:
        entries = [CostEntry.from_dict(e) for e in data.get("entries", [])]
        return cls(
            cost_card_id=UUID(data["cost_card_id"]),
            work_order_id=UUID(data["work_order_id"]),
            work_order_number=data["work_order_number"],
            product_id=UUID(data["product_id"]),
            product_code=data["product_code"],
            product_name=data["product_name"],
            planned_quantity=Decimal(data["planned_quantity"]),
            completed_quantity=Decimal(data["completed_quantity"]),
            material_cost=Decimal(data["material_cost"]),
            labor_cost=Decimal(data["labor_cost"]),
            overhead_cost=Decimal(data["overhead_cost"]),
            total_cost=Decimal(data["total_cost"]),
            unit_cost=Decimal(data["unit_cost"]),
            status=CostCardStatus.from_string(data["status"]),
            entries=entries,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )


# ==================== REPOSITORY PROTOCOL ====================


class CostCardRepository:
    async def get_by_id(self, cost_card_id: UUID, legal_entity_id: UUID) -> CostCardEntity | None:
        raise NotImplementedError

    async def get_by_work_order(
        self, work_order_id: UUID, legal_entity_id: UUID
    ) -> CostCardEntity | None:
        raise NotImplementedError

    async def get_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: CostCardStatus | None = None
    ) -> list[CostCardEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self, legal_entity_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[CostCardEntity]:
        raise NotImplementedError

    async def get_open_cost_cards(self, legal_entity_id: UUID) -> list[CostCardEntity]:
        raise NotImplementedError

    async def save(self, cost_card: CostCardEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, cost_card_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ==================== ALIAS ====================

CostCard = CostCardEntity

__all__ = [
    "CostCard",
    "CostCardEntity",
    "CostCardRepository",
    "CostCardStatus",
    "CostEntry",
]
