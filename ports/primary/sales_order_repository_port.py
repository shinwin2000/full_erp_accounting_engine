#!/usr/bin/env python3
"""
Module: sales_order_repository_port.py
Layer: Ports / Primary
Responsibility: Port for sales order repository operations.
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


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


class SalesOrderRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save(self, so: SalesOrderEntity) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, so_id: UUID) -> SalesOrderEntity | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_number(self, so_number: str) -> SalesOrderEntity | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[SalesOrderEntity]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_so_number(self, legal_entity_id: UUID) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(self, so_id: UUID, new_status: str, updated_by: UUID) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, so_id: UUID) -> None:
        raise NotImplementedError


class SalesOrderRepositoryPortProtocol(Protocol):
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


__all__ = [
    "SalesOrderEntity",
    "SalesOrderRepositoryPort",
    "SalesOrderRepositoryPortProtocol",
]
