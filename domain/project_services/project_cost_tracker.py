#!/usr/bin/env python3
"""
Module: project_cost_tracker.py
Layer: 6 - Domain / Project & Services
Responsibility: Pelacak biaya proyek.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.project_services.project_entity import ProjectEntity

logger = logging.getLogger(__name__)


class CostType(Enum):
    MATERIAL = "material"
    LABOR = "labor"
    SUBCONTRACTOR = "subcontractor"
    EQUIPMENT = "equipment"
    TRAVEL = "travel"
    OVERHEAD = "overhead"
    OTHER = "other"

    @classmethod
    def from_string(cls, value: str) -> CostType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.OTHER


@dataclass
class CostEntry:
    entry_id: UUID
    cost_type: CostType
    amount: Decimal
    quantity: Decimal
    unit_rate: Decimal
    date: datetime
    description: str
    vendor_id: UUID | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    reference_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Cost amount cannot be negative: {self.amount}")
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.quantity}")
        if self.unit_rate < 0:
            raise ValueError(f"Unit rate cannot be negative: {self.unit_rate}")
        if self.date.tzinfo is None:
            raise ValueError("date must be timezone-aware")
        if not self.description:
            raise ValueError("Description cannot be empty")

    @property
    def total_amount(self) -> Decimal:
        return self.amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "cost_type": self.cost_type.value,
            "amount": str(self.amount),
            "quantity": str(self.quantity),
            "unit_rate": str(self.unit_rate),
            "date": self.date.isoformat(),
            "description": self.description,
            "vendor_id": str(self.vendor_id) if self.vendor_id else None,
            "vendor_name": self.vendor_name,
            "invoice_number": self.invoice_number,
            "reference_id": str(self.reference_id) if self.reference_id else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostEntry:
        return cls(
            entry_id=UUID(data["entry_id"]),
            cost_type=CostType.from_string(data["cost_type"]),
            amount=Decimal(data["amount"]),
            quantity=Decimal(data["quantity"]),
            unit_rate=Decimal(data["unit_rate"]),
            date=datetime.fromisoformat(data["date"]),
            description=data["description"],
            vendor_id=UUID(data["vendor_id"]) if data.get("vendor_id") else None,
            vendor_name=data.get("vendor_name"),
            invoice_number=data.get("invoice_number"),
            reference_id=UUID(data["reference_id"]) if data.get("reference_id") else None,
        )


@dataclass
class ProjectCostTracker:
    tracker_id: UUID = field(default_factory=uuid4)
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    project_code: str = "UNKNOWN"
    project_name: str = "UNKNOWN"
    total_cost: Decimal = Decimal(0)
    material_cost: Decimal = Decimal(0)
    labor_cost: Decimal = Decimal(0)
    subcontractor_cost: Decimal = Decimal(0)
    equipment_cost: Decimal = Decimal(0)
    travel_cost: Decimal = Decimal(0)
    overhead_cost: Decimal = Decimal(0)
    other_cost: Decimal = Decimal(0)
    entries: list[CostEntry] = field(default_factory=list)
    last_update: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    created_by: str = "system"
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        # Pastikan total_cost konsisten dengan penjumlahan (opsional, bisa dilewat)
        # Tidak memaksa karena bisa di-set manual

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

    @classmethod
    def create(cls, project: ProjectEntity) -> ProjectCostTracker:
        return cls(
            tracker_id=uuid4(),
            project_id=project.project_id,
            project_code=project.project_code,
            project_name=project.project_name,
            total_cost=Decimal(0),
            material_cost=Decimal(0),
            labor_cost=Decimal(0),
            subcontractor_cost=Decimal(0),
            equipment_cost=Decimal(0),
            travel_cost=Decimal(0),
            overhead_cost=Decimal(0),
            other_cost=Decimal(0),
            created_by="system",
        )

    def add_cost(self, cost_entry: CostEntry, added_by: str) -> ProjectCostTracker:
        new_entries = self.entries + [cost_entry]

        new_material = self.material_cost
        new_labor = self.labor_cost
        new_subcontractor = self.subcontractor_cost
        new_equipment = self.equipment_cost
        new_travel = self.travel_cost
        new_overhead = self.overhead_cost
        new_other = self.other_cost

        if cost_entry.cost_type == CostType.MATERIAL:
            new_material += cost_entry.amount
        elif cost_entry.cost_type == CostType.LABOR:
            new_labor += cost_entry.amount
        elif cost_entry.cost_type == CostType.SUBCONTRACTOR:
            new_subcontractor += cost_entry.amount
        elif cost_entry.cost_type == CostType.EQUIPMENT:
            new_equipment += cost_entry.amount
        elif cost_entry.cost_type == CostType.TRAVEL:
            new_travel += cost_entry.amount
        elif cost_entry.cost_type == CostType.OVERHEAD:
            new_overhead += cost_entry.amount
        else:
            new_other += cost_entry.amount

        new_total = (
            new_material
            + new_labor
            + new_subcontractor
            + new_equipment
            + new_travel
            + new_overhead
            + new_other
        )

        self._record_audit(
            "cost_added",
            added_by,
            {
                "cost_type": cost_entry.cost_type.value,
                "amount": str(cost_entry.amount),
                "description": cost_entry.description,
            },
        )

        return ProjectCostTracker(
            tracker_id=self.tracker_id,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            total_cost=new_total,
            material_cost=new_material,
            labor_cost=new_labor,
            subcontractor_cost=new_subcontractor,
            equipment_cost=new_equipment,
            travel_cost=new_travel,
            overhead_cost=new_overhead,
            other_cost=new_other,
            entries=new_entries,
            last_update=datetime.now(UTC),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def get_cost_by_type(self, cost_type: CostType) -> Decimal:
        if cost_type == CostType.MATERIAL:
            return self.material_cost
        elif cost_type == CostType.LABOR:
            return self.labor_cost
        elif cost_type == CostType.SUBCONTRACTOR:
            return self.subcontractor_cost
        elif cost_type == CostType.EQUIPMENT:
            return self.equipment_cost
        elif cost_type == CostType.TRAVEL:
            return self.travel_cost
        elif cost_type == CostType.OVERHEAD:
            return self.overhead_cost
        else:
            return self.other_cost

    def get_cost_breakdown(self) -> dict[str, Decimal]:
        return {
            "material": self.material_cost,
            "labor": self.labor_cost,
            "subcontractor": self.subcontractor_cost,
            "equipment": self.equipment_cost,
            "travel": self.travel_cost,
            "overhead": self.overhead_cost,
            "other": self.other_cost,
            "total": self.total_cost,
        }

    def get_entries_by_date_range(self, from_date: datetime, to_date: datetime) -> list[CostEntry]:
        return [e for e in self.entries if from_date <= e.date <= to_date]

    def get_entries_by_type(self, cost_type: CostType) -> list[CostEntry]:
        return [e for e in self.entries if e.cost_type == cost_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tracker_id": str(self.tracker_id),
            "project_id": str(self.project_id),
            "project_code": self.project_code,
            "project_name": self.project_name,
            "total_cost": str(self.total_cost),
            "cost_breakdown": self.get_cost_breakdown(),
            "entries_count": len(self.entries),
            "last_update": self.last_update.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectCostTracker:
        entries = [CostEntry.from_dict(e) for e in data.get("entries", [])]
        return cls(
            tracker_id=UUID(data["tracker_id"]),
            project_id=UUID(data["project_id"]),
            project_code=data["project_code"],
            project_name=data["project_name"],
            total_cost=Decimal(data["total_cost"]),
            material_cost=Decimal(data.get("material_cost", "0")),
            labor_cost=Decimal(data.get("labor_cost", "0")),
            subcontractor_cost=Decimal(data.get("subcontractor_cost", "0")),
            equipment_cost=Decimal(data.get("equipment_cost", "0")),
            travel_cost=Decimal(data.get("travel_cost", "0")),
            overhead_cost=Decimal(data.get("overhead_cost", "0")),
            other_cost=Decimal(data.get("other_cost", "0")),
            entries=entries,
            last_update=datetime.fromisoformat(data["last_update"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )


class ProjectCostTrackerRepository:
    async def get_by_project(
        self, project_id: UUID, legal_entity_id: UUID
    ) -> ProjectCostTracker | None:
        raise NotImplementedError

    async def save(self, tracker: ProjectCostTracker, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, tracker_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "CostEntry",
    "CostType",
    "ProjectCostTracker",
    "ProjectCostTrackerRepository",
]