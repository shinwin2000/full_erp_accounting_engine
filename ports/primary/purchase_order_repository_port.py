#!/usr/bin/env python3
"""
Module: purchase_order_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for purchase order repository operations.

Defines the contract for:
- Saving and retrieving purchase orders
- Purchase order items
- Approval workflows
- Receiving and matching
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


class PurchaseOrderEntity:
    """Represents a purchase order (simplified)."""

    def __init__(
        self,
        id: UUID,
        po_number: str,
        legal_entity_id: UUID,
        supplier_id: UUID,
        supplier_name: str,
        order_date: date,
        expected_delivery_date: date | None,
        currency: str,
        total_amount: Decimal,
        status: str,  # DRAFT, SUBMITTED, APPROVED, RECEIVED, CANCELLED, CLOSED
        created_by: UUID,
        created_at: datetime,
        items: list[dict[str, Any]] | None = None,
        approval_date: datetime | None = None,
        approved_by: UUID | None = None,
        notes: str | None = None,
    ):
        self.id = id
        self.po_number = po_number
        self.legal_entity_id = legal_entity_id
        self.supplier_id = supplier_id
        self.supplier_name = supplier_name
        self.order_date = order_date
        self.expected_delivery_date = expected_delivery_date
        self.currency = currency
        self.total_amount = total_amount
        self.status = status
        self.created_by = created_by
        self.created_at = created_at
        self.items = items or []
        self.approval_date = approval_date
        self.approved_by = approved_by
        self.notes = notes


class PurchaseOrderRepositoryPort(abc.ABC):
    """
    Port for purchase order persistence.
    """

    @abc.abstractmethod
    async def save(self, po: PurchaseOrderEntity) -> None:
        """Save or update a purchase order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, po_id: UUID) -> PurchaseOrderEntity | None:
        """Retrieve purchase order by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_number(self, po_number: str) -> PurchaseOrderEntity | None:
        """Retrieve purchase order by PO number."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_supplier(
        self, supplier_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[PurchaseOrderEntity]:
        """List purchase orders for a supplier."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[PurchaseOrderEntity]:
        """List purchase orders by status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[PurchaseOrderEntity]:
        """List purchase orders within a date range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_po_number(self, legal_entity_id: UUID) -> str | None:
        """Get the last used purchase order number for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(self, po_id: UUID, new_status: str, updated_by: UUID) -> None:
        """Update the status of a purchase order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, po_id: UUID) -> None:
        """Delete a purchase order (only if in DRAFT)."""
        raise NotImplementedError


class PurchaseOrderRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def save(self, po: PurchaseOrderEntity) -> None: ...
    async def get_by_id(self, po_id: UUID) -> PurchaseOrderEntity | None: ...
    async def get_by_number(self, po_number: str) -> PurchaseOrderEntity | None: ...
    async def list_by_supplier(
        self, supplier_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[PurchaseOrderEntity]: ...
    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[PurchaseOrderEntity]: ...
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[PurchaseOrderEntity]: ...
    async def get_last_po_number(self, legal_entity_id: UUID) -> str | None: ...
    async def update_status(self, po_id: UUID, new_status: str, updated_by: UUID) -> None: ...
    async def delete(self, po_id: UUID) -> None: ...


__all__ = [
    "PurchaseOrderEntity",
    "PurchaseOrderRepositoryPort",
    "PurchaseOrderRepositoryPortProtocol",
]
