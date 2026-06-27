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

# ============================================================================
# INTERFACE
# ============================================================================


class SalesRepositoryPort(ABC):
    """
    Interface untuk repository sales.
    """

    @abstractmethod
    async def save_transaction(self, transaction: Any) -> None:
        """Save a sales transaction."""
        pass

    @abstractmethod
    async def get_by_id(self, transaction_id: UUID) -> Any | None:
        """Get sales transaction by ID."""
        pass

    @abstractmethod
    async def get_by_number(self, transaction_number: str, legal_entity_id: UUID) -> Any | None:
        """Get sales transaction by transaction number."""
        pass

    @abstractmethod
    async def list_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> list[Any]:
        """List sales transactions within a period."""
        pass

    @abstractmethod
    async def list_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]:
        """List sales transactions by customer."""
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
    ) -> list[Any]:
        """Search sales transactions by keyword."""
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


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["SalesRepositoryPort"]
