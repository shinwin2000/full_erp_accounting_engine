# manufacturing_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: manufacturing_request.py
Layer: Application DTO
Responsibility: Data Transfer Objects for manufacturing commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === ENUMS ===


class WorkOrderStatus(str, Enum):
    """Status work order."""

    DRAFT = "draft"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class ManufacturingOrderType(str, Enum):
    """Type of manufacturing order."""

    STANDARD = "standard"
    CUSTOM = "custom"
    REPAIR = "repair"
    PROTOTYPE = "prototype"


# === DTOs ===


@dataclass(kw_only=True)
class WorkOrderCreateRequest:
    """DTO untuk membuat work order baru."""

    work_order_number: str
    product_id: UUID
    product_name: str
    planned_quantity: Decimal
    bom_id: UUID
    routing_id: UUID | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    legal_entity_id: UUID | None = None
    created_by: UUID | None = None
    description: str | None = None
    cost_center: str | None = None
    standard_cost: Decimal | None = None
    priority: int = 1
    order_type: ManufacturingOrderType = ManufacturingOrderType.STANDARD

    def __post_init__(self) -> None:
        if self.planned_quantity <= 0:
            raise ValueError(f"Planned quantity must be positive: {self.planned_quantity}")
        if not self.product_name:
            raise ValueError("Product name is required")
        if self.priority < 1 or self.priority > 5:
            raise ValueError("Priority must be between 1 and 5")

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_name": self.product_name,
            "planned_quantity": str(self.planned_quantity),
            "bom_id": str(self.bom_id),
            "routing_id": str(self.routing_id) if self.routing_id else None,
            "planned_start_date": self.planned_start_date.isoformat()
            if self.planned_start_date
            else None,
            "planned_end_date": self.planned_end_date.isoformat()
            if self.planned_end_date
            else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "description": self.description,
            "cost_center": self.cost_center,
            "standard_cost": str(self.standard_cost) if self.standard_cost else None,
            "priority": self.priority,
            "order_type": self.order_type.value,
        }


@dataclass(kw_only=True)
class MaterialIssueRequest:
    """DTO untuk issue material ke produksi."""

    work_order_id: UUID
    material_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    issue_date: date
    issued_by: UUID | None = None
    legal_entity_id: UUID | None = None
    bin_location: str | None = None
    batch_number: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "material_id": str(self.material_id),
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "issue_date": self.issue_date.isoformat(),
            "issued_by": str(self.issued_by) if self.issued_by else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "bin_location": self.bin_location,
            "batch_number": self.batch_number,
            "notes": self.notes,
        }

    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost of material issued."""
        return self.quantity * self.unit_cost


@dataclass(kw_only=True)
class LaborRecordRequest:
    """DTO untuk mencatat tenaga kerja."""

    work_order_id: UUID
    employee_id: UUID
    hours: Decimal
    hourly_rate: Decimal
    labor_date: date
    recorded_by: UUID | None = None
    legal_entity_id: UUID | None = None
    operation_code: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.hours <= 0:
            raise ValueError(f"Hours must be positive: {self.hours}")
        if self.hourly_rate < 0:
            raise ValueError(f"Hourly rate cannot be negative: {self.hourly_rate}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "employee_id": str(self.employee_id),
            "hours": str(self.hours),
            "hourly_rate": str(self.hourly_rate),
            "labor_date": self.labor_date.isoformat(),
            "recorded_by": str(self.recorded_by) if self.recorded_by else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "operation_code": self.operation_code,
            "notes": self.notes,
        }

    @property
    def total_cost(self) -> Decimal:
        """Calculate total labor cost."""
        return self.hours * self.hourly_rate


@dataclass(kw_only=True)
class ProductionCompletionRequest:
    """DTO untuk menyelesaikan produksi."""

    work_order_id: UUID
    completed_quantity: Decimal
    rejected_quantity: Decimal
    completion_date: date
    unit_cost: Decimal
    total_cost: Decimal
    completed_by: UUID | None = None
    legal_entity_id: UUID | None = None
    remarks: str | None = None

    def __post_init__(self) -> None:
        if self.completed_quantity <= 0:
            raise ValueError(f"Completed quantity must be positive: {self.completed_quantity}")
        if self.rejected_quantity < 0:
            raise ValueError(f"Rejected quantity cannot be negative: {self.rejected_quantity}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "completed_quantity": str(self.completed_quantity),
            "rejected_quantity": str(self.rejected_quantity),
            "completion_date": self.completion_date.isoformat(),
            "unit_cost": str(self.unit_cost),
            "total_cost": str(self.total_cost),
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "remarks": self.remarks,
        }

    @property
    def total_quantity(self) -> Decimal:
        """Get total quantity processed."""
        return self.completed_quantity + self.rejected_quantity

    @property
    def yield_rate(self) -> Decimal:
        """Calculate yield rate (completed / total)."""
        if self.total_quantity > 0:
            return (self.completed_quantity / self.total_quantity) * 100
        return Decimal(0)


@dataclass(kw_only=True)
class UpdateWorkOrderRequest:
    """DTO untuk mengupdate work order."""

    work_order_id: UUID
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    priority: int | None = None
    status: WorkOrderStatus | None = None
    description: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.planned_start_date,
                self.planned_end_date,
                self.priority,
                self.status,
                self.description,
                self.notes,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.priority is not None and (self.priority < 1 or self.priority > 5):
            raise ValueError("Priority must be between 1 and 5")

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "planned_start_date": self.planned_start_date.isoformat()
            if self.planned_start_date
            else None,
            "planned_end_date": self.planned_end_date.isoformat()
            if self.planned_end_date
            else None,
            "priority": self.priority,
            "status": self.status.value if self.status else None,
            "description": self.description,
            "notes": self.notes,
        }


@dataclass(kw_only=True)
class GetWorkOrderRequest:
    """DTO untuk mendapatkan work order."""

    work_order_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


@dataclass(kw_only=True)
class ListWorkOrdersRequest:
    """DTO untuk list work orders dengan filter."""

    legal_entity_id: UUID
    status: WorkOrderStatus | None = None
    product_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status.value if self.status else None,
            "product_id": str(self.product_id) if self.product_id else None,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(kw_only=True)
class ManufacturingCostSummaryRequest:
    """DTO untuk ringkasan biaya manufacturing."""

    work_order_id: UUID
    legal_entity_id: UUID
    as_of_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
        }


# === Factory ===


class ManufacturingRequestFactory:
    """Factory untuk membuat Manufacturing Request DTOs."""

    @staticmethod
    def create_work_order(
        work_order_number: str,
        product_id: UUID,
        product_name: str,
        planned_quantity: Decimal,
        bom_id: UUID,
        legal_entity_id: UUID,
        created_by: UUID,
        planned_start_date: date | None = None,
        planned_end_date: date | None = None,
    ) -> WorkOrderCreateRequest:
        """Create a work order create request."""
        return WorkOrderCreateRequest(
            work_order_number=work_order_number,
            product_id=product_id,
            product_name=product_name,
            planned_quantity=planned_quantity,
            bom_id=bom_id,
            legal_entity_id=legal_entity_id,
            created_by=created_by,
            planned_start_date=planned_start_date,
            planned_end_date=planned_end_date,
        )

    @staticmethod
    def create_material_issue(
        work_order_id: UUID,
        material_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal,
        issue_date: date,
        issued_by: UUID,
    ) -> MaterialIssueRequest:
        """Create a material issue request."""
        return MaterialIssueRequest(
            work_order_id=work_order_id,
            material_id=material_id,
            quantity=quantity,
            unit_cost=unit_cost,
            issue_date=issue_date,
            issued_by=issued_by,
        )

    @staticmethod
    def create_labor_record(
        work_order_id: UUID,
        employee_id: UUID,
        hours: Decimal,
        hourly_rate: Decimal,
        labor_date: date,
        recorded_by: UUID,
    ) -> LaborRecordRequest:
        """Create a labor record request."""
        return LaborRecordRequest(
            work_order_id=work_order_id,
            employee_id=employee_id,
            hours=hours,
            hourly_rate=hourly_rate,
            labor_date=labor_date,
            recorded_by=recorded_by,
        )


# === Aliases for backward compatibility ===
WorkOrderRequest = WorkOrderCreateRequest
MaterialIssueDTO = MaterialIssueRequest
LaborRecordDTO = LaborRecordRequest
ProductionCompletionDTO = ProductionCompletionRequest


# === Exports ===
__all__ = [
    "GetWorkOrderRequest",
    "LaborRecordDTO",
    "LaborRecordRequest",
    "ListWorkOrdersRequest",
    "ManufacturingCostSummaryRequest",
    "ManufacturingOrderType",
    "ManufacturingRequestFactory",
    "MaterialIssueDTO",
    "MaterialIssueRequest",
    "ProductionCompletionDTO",
    "ProductionCompletionRequest",
    "UpdateWorkOrderRequest",
    "WorkOrderCreateRequest",
    "WorkOrderRequest",
    "WorkOrderStatus",
]
