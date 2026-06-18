#!/usr/bin/env python3
"""
Module: work_order_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for work order repository operations.

Defines the contract for:
- Saving and retrieving work orders
- Work order status updates
- Work order items and tracking
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


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


class WorkOrderRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save(self, work_order: WorkOrderEntity) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, work_order: WorkOrderEntity) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, wo_id: UUID) -> WorkOrderEntity | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_number(self, wo_number: str) -> WorkOrderEntity | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[WorkOrderEntity]:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: str | None = None
    ) -> list[WorkOrderEntity]:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_wo_number(self, legal_entity_id: UUID) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(self, wo_id: UUID, new_status: str, updated_by: UUID) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, wo_id: UUID) -> None:
        raise NotImplementedError


class WorkOrderRepositoryPortProtocol(Protocol):
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


__all__ = [
    "WorkOrderEntity",
    "WorkOrderRepositoryPort",
    "WorkOrderRepositoryPortProtocol",
]
