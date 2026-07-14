#!/usr/bin/env python3
"""
Module: sales_order_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository sales order.
    - Menyediakan implementasi in-memory untuk testing/fallback.
"""

from __future__ import annotations

import abc
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

# ==================== DOMAIN ENTITY ====================

class SalesOrderEntity:
    """Represents a sales order (simplified)."""

    def __init__(
        self,
        id: UUID,
        so_number: str,
        legal_entity_id: UUID,
        customer_id: UUID,
        customer_name: str,
        order_date: date,
        requested_delivery_date: date | None,
        currency: str,
        total_amount: Decimal,
        status: str,  # DRAFT, SUBMITTED, APPROVED, SHIPPED, INVOICED, CANCELLED, CLOSED
        created_by: UUID,
        created_at: datetime,
        items: list[dict[str, Any]] | None = None,
        approval_date: datetime | None = None,
        approved_by: UUID | None = None,
        notes: str | None = None,
    ):
        self.id = id
        self.so_number = so_number
        self.legal_entity_id = legal_entity_id
        self.customer_id = customer_id
        self.customer_name = customer_name
        self.order_date = order_date
        self.requested_delivery_date = requested_delivery_date
        self.currency = currency
        self.total_amount = total_amount
        self.status = status
        self.created_by = created_by
        self.created_at = created_at
        self.items = items or []
        self.approval_date = approval_date
        self.approved_by = approved_by
        self.notes = notes


# ==================== PORT (INTERFACE) ====================

class SalesOrderRepositoryPort(abc.ABC):
    """Port for sales order data persistence."""

    @abc.abstractmethod
    async def save(self, so: SalesOrderEntity) -> None:
        """Save a new sales order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, so_id: UUID) -> SalesOrderEntity | None:
        """Get sales order by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_number(self, so_number: str) -> SalesOrderEntity | None:
        """Get sales order by number."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        """List sales orders for a customer."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        """List sales orders by status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[SalesOrderEntity]:
        """List sales orders within a date range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_so_number(self, legal_entity_id: UUID) -> str | None:
        """Get the last used sales order number for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(self, so_id: UUID, new_status: str, updated_by: UUID) -> None:
        """Update sales order status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, so_id: UUID) -> None:
        """Delete a sales order (only if DRAFT)."""
        raise NotImplementedError


class SalesOrderRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""
    async def save(self, so: SalesOrderEntity) -> None: ...
    async def get_by_id(self, so_id: UUID) -> SalesOrderEntity | None: ...
    async def get_by_number(self, so_number: str) -> SalesOrderEntity | None: ...
    async def list_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]: ...
    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]: ...
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[SalesOrderEntity]: ...
    async def get_last_so_number(self, legal_entity_id: UUID) -> str | None: ...
    async def update_status(self, so_id: UUID, new_status: str, updated_by: UUID) -> None: ...
    async def delete(self, so_id: UUID) -> None: ...


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemorySalesOrderRepository(SalesOrderRepositoryPort):
    """
    Implementasi in-memory untuk repository sales order.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._orders: dict[UUID, SalesOrderEntity] = {}
        self._orders_by_number: dict[str, UUID] = {}
        self._lock = asyncio.Lock()

    async def save(self, so: SalesOrderEntity) -> None:
        async with self._lock:
            if so.id in self._orders:
                raise ValueError(f"Sales order {so.id} already exists. Use update?")
            self._orders[so.id] = so
            self._orders_by_number[so.so_number] = so.id

    async def get_by_id(self, so_id: UUID) -> SalesOrderEntity | None:
        async with self._lock:
            return self._orders.get(so_id)

    async def get_by_number(self, so_number: str) -> SalesOrderEntity | None:
        async with self._lock:
            so_id = self._orders_by_number.get(so_number)
            if so_id:
                return self._orders.get(so_id)
            return None

    async def list_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        async with self._lock:
            result = []
            for so in self._orders.values():
                if so.legal_entity_id != legal_entity_id:
                    continue
                if so.customer_id != customer_id:
                    continue
                result.append(so)
            result.sort(key=lambda x: x.created_at, reverse=True)
            return result[offset:offset + limit]

    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        async with self._lock:
            result = []
            for so in self._orders.values():
                if so.legal_entity_id != legal_entity_id:
                    continue
                if so.status != status:
                    continue
                result.append(so)
            result.sort(key=lambda x: x.created_at, reverse=True)
            return result[offset:offset + limit]

    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[SalesOrderEntity]:
        async with self._lock:
            result = []
            for so in self._orders.values():
                if so.legal_entity_id != legal_entity_id:
                    continue
                if not (from_date <= so.order_date <= to_date):
                    continue
                result.append(so)
            result.sort(key=lambda x: x.order_date, reverse=True)
            return result[:limit]

    async def get_last_so_number(self, legal_entity_id: UUID) -> str | None:
        async with self._lock:
            numbers = []
            for so in self._orders.values():
                if so.legal_entity_id == legal_entity_id:
                    numbers.append(so.so_number)
            if not numbers:
                return None
            numbers.sort()
            return numbers[-1]

    async def update_status(self, so_id: UUID, new_status: str, updated_by: UUID) -> None:
        async with self._lock:
            so = self._orders.get(so_id)
            if not so:
                raise ValueError(f"Sales order {so_id} not found.")
            so.status = new_status
            # Optionally track approval
            if new_status == "APPROVED":
                so.approval_date = datetime.utcnow()
                so.approved_by = updated_by

    async def delete(self, so_id: UUID) -> None:
        async with self._lock:
            so = self._orders.get(so_id)
            if not so:
                return
            if so.status != "DRAFT":
                raise ValueError("Cannot delete a sales order that is not in DRAFT status.")
            del self._orders[so_id]
            if so.so_number in self._orders_by_number:
                del self._orders_by_number[so.so_number]


# ==================== EXPORTS ====================

__all__ = [
    "InMemorySalesOrderRepository",
    "SalesOrderEntity",
    "SalesOrderRepositoryPort",
    "SalesOrderRepositoryPortProtocol",
]
