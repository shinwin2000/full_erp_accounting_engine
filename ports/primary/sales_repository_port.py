#!/usr/bin/env python3
"""
Module: sales_repository_port.py
Layer: Ports (Primary)
Responsibility: Interface repository untuk operasi sales.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any
from uuid import UUID

# Import SalesOrderEntity dari port sales order (agar konsisten)
from ports.primary.sales_order_repository_port import SalesOrderEntity


class SalesRepositoryPort(ABC):
    """
    Interface untuk repository sales.
    Semua return type menggunakan SalesOrderEntity (konsisten dengan implementasi SQLAlchemy).
    """

    @abstractmethod
    async def save_transaction(self, transaction: Any) -> None:
        """Save a sales transaction (expects SalesOrderEntity or dict)."""
        pass

    @abstractmethod
    async def get_by_id(self, transaction_id: UUID) -> SalesOrderEntity | None:
        """Get sales transaction by ID, return SalesOrderEntity or None."""
        pass

    @abstractmethod
    async def get_by_number(self, so_number: str, legal_entity_id: UUID) -> SalesOrderEntity | None:
        """
        Get sales transaction by SO number.
        Parameter 'so_number' konsisten dengan database dan implementasi.
        """
        pass

    @abstractmethod
    async def list_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> list[SalesOrderEntity]:
        """List sales transactions within a period, return list of SalesOrderEntity."""
        pass

    @abstractmethod
    async def list_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SalesOrderEntity]:
        """List sales transactions by customer, return list of SalesOrderEntity."""
        pass

    @abstractmethod
    async def delete_transaction(self, transaction_id: UUID) -> bool:
        """Delete a sales transaction (soft delete)."""
        pass

    @abstractmethod
    async def exists(self, transaction_id: UUID) -> bool:
        """Check if transaction exists."""
        pass

    @abstractmethod
    async def count_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> int:
        """Count transactions in a period."""
        pass

    @abstractmethod
    async def get_last_transaction_number(self, legal_entity_id: UUID) -> str | None:
        """Get the last transaction number for generating next number."""
        pass

    @abstractmethod
    async def search(
        self,
        legal_entity_id: UUID,
        query: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SalesOrderEntity]:
        """Search sales transactions by keyword, return list of SalesOrderEntity."""
        pass

    @abstractmethod
    async def get_total_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Get sales totals (total amount, count) for a period."""
        pass


__all__ = ["SalesRepositoryPort"]