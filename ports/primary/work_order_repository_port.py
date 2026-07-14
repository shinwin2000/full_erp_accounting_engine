#!/usr/bin/env python3
"""
Module: work_order_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository work order.
    - Menyediakan implementasi in-memory untuk testing/fallback.

Defines the contract for:
- Saving and retrieving work orders
- Work order status updates
- Work order items and tracking
"""

from __future__ import annotations

import abc
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

# ==================== DOMAIN ENTITY ====================

class WorkOrderEntity:
    """Represents a work order (simplified)."""

    def __init__(
        self,
        id: UUID,
        wo_number: str,
        legal_entity_id: UUID,
        product_id: UUID,
        product_code: str,
        product_name: str,
        planned_quantity: Decimal,
        completed_quantity: Decimal,
        status: str,  # DRAFT, APPROVED, IN_PROGRESS, COMPLETED, CANCELLED
        planned_start_date: date,
        planned_end_date: date,
        actual_start_date: date | None = None,
        actual_end_date: date | None = None,
        bom_id: UUID | None = None,
        routing_id: UUID | None = None,
        created_by: UUID | None = None,
        created_at: datetime | None = None,
        notes: str | None = None,
    ):
        self.id = id
        self.wo_number = wo_number
        self.legal_entity_id = legal_entity_id
        self.product_id = product_id
        self.product_code = product_code
        self.product_name = product_name
        self.planned_quantity = planned_quantity
        self.completed_quantity = completed_quantity
        self.status = status
        self.planned_start_date = planned_start_date
        self.planned_end_date = planned_end_date
        self.actual_start_date = actual_start_date
        self.actual_end_date = actual_end_date
        self.bom_id = bom_id
        self.routing_id = routing_id
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()
        self.notes = notes


# ==================== PORT (INTERFACE) ====================

class WorkOrderRepositoryPort(abc.ABC):
    """Port for work order data persistence."""

    @abc.abstractmethod
    async def save(self, work_order: WorkOrderEntity) -> None:
        """Save a new work order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, work_order: WorkOrderEntity) -> None:
        """Update an existing work order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, wo_id: UUID) -> WorkOrderEntity | None:
        """Get work order by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_number(self, wo_number: str) -> WorkOrderEntity | None:
        """Get work order by number."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[WorkOrderEntity]:
        """List work orders for a legal entity, optionally filtered by status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: str | None = None
    ) -> list[WorkOrderEntity]:
        """List work orders for a product, optionally filtered by status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]:
        """List work orders within a date range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_wo_number(self, legal_entity_id: UUID) -> str | None:
        """Get the last used work order number for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(self, wo_id: UUID, new_status: str, updated_by: UUID) -> None:
        """Update work order status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, wo_id: UUID) -> None:
        """Delete a work order (only if DRAFT)."""
        raise NotImplementedError


class WorkOrderRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""
    async def save(self, work_order: WorkOrderEntity) -> None: ...
    async def update(self, work_order: WorkOrderEntity) -> None: ...
    async def get_by_id(self, wo_id: UUID) -> WorkOrderEntity | None: ...
    async def get_by_number(self, wo_number: str) -> WorkOrderEntity | None: ...
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[WorkOrderEntity]: ...
    async def list_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: str | None = None
    ) -> list[WorkOrderEntity]: ...
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]: ...
    async def get_last_wo_number(self, legal_entity_id: UUID) -> str | None: ...
    async def update_status(self, wo_id: UUID, new_status: str, updated_by: UUID) -> None: ...
    async def delete(self, wo_id: UUID) -> None: ...


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemoryWorkOrderRepository(WorkOrderRepositoryPort):
    """
    Implementasi in-memory untuk repository work order.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._work_orders: dict[UUID, WorkOrderEntity] = {}
        self._work_orders_by_number: dict[str, UUID] = {}
        self._lock = asyncio.Lock()

    async def save(self, work_order: WorkOrderEntity) -> None:
        async with self._lock:
            if work_order.id in self._work_orders:
                raise ValueError(f"Work order {work_order.id} already exists. Use update() instead.")
            self._work_orders[work_order.id] = work_order
            self._work_orders_by_number[work_order.wo_number] = work_order.id

    async def update(self, work_order: WorkOrderEntity) -> None:
        async with self._lock:
            if work_order.id not in self._work_orders:
                raise ValueError(f"Work order {work_order.id} not found.")
            old = self._work_orders[work_order.id]
            if old.wo_number != work_order.wo_number:
                # Remove old number mapping
                del self._work_orders_by_number[old.wo_number]
                self._work_orders_by_number[work_order.wo_number] = work_order.id
            self._work_orders[work_order.id] = work_order

    async def get_by_id(self, wo_id: UUID) -> WorkOrderEntity | None:
        async with self._lock:
            return self._work_orders.get(wo_id)

    async def get_by_number(self, wo_number: str) -> WorkOrderEntity | None:
        async with self._lock:
            wo_id = self._work_orders_by_number.get(wo_number)
            if wo_id:
                return self._work_orders.get(wo_id)
            return None

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[WorkOrderEntity]:
        async with self._lock:
            result = []
            for wo in self._work_orders.values():
                if wo.legal_entity_id != legal_entity_id:
                    continue
                if status and wo.status != status:
                    continue
                result.append(wo)
            result.sort(key=lambda x: x.created_at, reverse=True)
            return result[offset:offset + limit]

    async def list_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: str | None = None
    ) -> list[WorkOrderEntity]:
        async with self._lock:
            result = []
            for wo in self._work_orders.values():
                if wo.product_id != product_id:
                    continue
                if wo.legal_entity_id != legal_entity_id:
                    continue
                if status and wo.status != status:
                    continue
                result.append(wo)
            result.sort(key=lambda x: x.created_at, reverse=True)
            return result

    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]:
        async with self._lock:
            result = []
            for wo in self._work_orders.values():
                if wo.legal_entity_id != legal_entity_id:
                    continue
                if not (from_date <= wo.planned_start_date <= to_date):
                    continue
                result.append(wo)
            result.sort(key=lambda x: x.planned_start_date)
            return result

    async def get_last_wo_number(self, legal_entity_id: UUID) -> str | None:
        async with self._lock:
            numbers = []
            for wo in self._work_orders.values():
                if wo.legal_entity_id == legal_entity_id:
                    numbers.append(wo.wo_number)
            if not numbers:
                return None
            numbers.sort()
            return numbers[-1]

    async def update_status(self, wo_id: UUID, new_status: str, updated_by: UUID) -> None:
        async with self._lock:
            wo = self._work_orders.get(wo_id)
            if not wo:
                raise ValueError(f"Work order {wo_id} not found.")
            wo.status = new_status

    async def delete(self, wo_id: UUID) -> None:
        async with self._lock:
            wo = self._work_orders.get(wo_id)
            if not wo:
                return
            if wo.status != "DRAFT":
                raise ValueError("Cannot delete a work order that is not in DRAFT status.")
            del self._work_orders[wo_id]
            if wo.wo_number in self._work_orders_by_number:
                del self._work_orders_by_number[wo.wo_number]


# ==================== EXPORTS ====================

__all__ = [
    "InMemoryWorkOrderRepository",
    "WorkOrderEntity",
    "WorkOrderRepositoryPort",
    "WorkOrderRepositoryPortProtocol",
]
