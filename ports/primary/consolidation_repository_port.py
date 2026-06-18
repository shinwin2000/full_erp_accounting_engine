#!/usr/bin/env python3
"""
Module: consolidation_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for consolidation operations.

Defines the contract for consolidation repository:
- Save and retrieve consolidation results
- Manage intercompany transactions
- Elimination entries
- Intercompany balances
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from domain.consolidation.elimination_entry import EliminationEntry

# Domain entities (these must exist, but if not, we define stubs)
from domain.consolidation.intercompany_transaction import IntercompanyTransaction


class ConsolidationRepositoryPort(abc.ABC):
    """
    Port for consolidation persistence.
    All methods must be implemented by concrete adapters.
    """

    # --------------------------------------------------------------------
    # Intercompany Transactions
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def get_intercompany_transactions(
        self, entity_ids: list[UUID], as_of_date: date
    ) -> list[IntercompanyTransaction]:
        """Get all intercompany transactions between entities up to a date."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_intercompany_balances(self, entity_id: UUID, as_of_date: date) -> list[Any]:
        """Get intercompany balances for an entity as of a date."""
        raise NotImplementedError

    @abc.abstractmethod
    async def save_intercompany_transaction(self, tx: IntercompanyTransaction) -> None:
        """Save an intercompany transaction."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Consolidation Results
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_consolidation(
        self,
        id: UUID,
        group_entity_id: UUID,
        period_end_date: date,
        currency: str,
        rows: list[Any],
        eliminations: list[EliminationEntry],
        nci_total: Decimal,
        created_at: datetime,
    ) -> None:
        """Save a consolidation result."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_consolidation(self, consolidation_id: UUID) -> Any | None:
        """Retrieve a consolidation result by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_consolidations(
        self, group_entity_id: UUID, from_date: date | None = None, to_date: date | None = None
    ) -> list[Any]:
        """List consolidations for a group entity."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Utility methods for consolidation preparation
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def get_ownership_percentage(self, parent_id: UUID, child_id: UUID) -> Decimal:
        """Get ownership percentage of parent in child entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_entity_equity(self, entity_id: UUID, as_of_date: date) -> Decimal:
        """Get total equity of an entity as of date (from trial balance)."""
        raise NotImplementedError


class ConsolidationRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def get_intercompany_transactions(
        self, entity_ids: list[UUID], as_of_date: date
    ) -> list[IntercompanyTransaction]: ...
    async def get_intercompany_balances(self, entity_id: UUID, as_of_date: date) -> list[Any]: ...
    async def save_intercompany_transaction(self, tx: IntercompanyTransaction) -> None: ...
    async def save_consolidation(
        self,
        id: UUID,
        group_entity_id: UUID,
        period_end_date: date,
        currency: str,
        rows: list[Any],
        eliminations: list[EliminationEntry],
        nci_total: Decimal,
        created_at: datetime,
    ) -> None: ...
    async def get_consolidation(self, consolidation_id: UUID) -> Any | None: ...
    async def list_consolidations(
        self, group_entity_id: UUID, from_date: date | None = None, to_date: date | None = None
    ) -> list[Any]: ...
    async def get_ownership_percentage(self, parent_id: UUID, child_id: UUID) -> Decimal: ...
    async def get_entity_equity(self, entity_id: UUID, as_of_date: date) -> Decimal: ...


__all__ = [
    "ConsolidationRepositoryPort",
    "ConsolidationRepositoryPortProtocol",
]
