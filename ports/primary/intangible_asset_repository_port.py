#!/usr/bin/env python3
"""
Module: intangible_asset_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for intangible asset repository.

Defines the contract for:
- Saving and retrieving intangible assets
- Amortization schedules
- Impairment and revaluation records
- Asset disposal
"""

from __future__ import annotations

import abc
from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from domain.intangible_asset.aggregate_root import IntangibleAsset

# Domain entities (if available, otherwise define here)
from domain.intangible_asset.asset_entity import IntangibleAssetEntity


class IntangibleAssetRepositoryPort(abc.ABC):
    """
    Port for intangible asset repository operations.
    All methods must be implemented by concrete adapters.
    """

    # --------------------------------------------------------------------
    # Basic CRUD operations
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save(self, asset: IntangibleAssetEntity) -> None:
        """Save or update an intangible asset."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update(self, asset: IntangibleAssetEntity) -> None:
        """Update an existing intangible asset."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, asset_id: UUID) -> IntangibleAssetEntity | None:
        """Retrieve an intangible asset by its ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, include_inactive: bool = False
    ) -> list[IntangibleAssetEntity]:
        """List all intangible assets for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_active_assets_for_amortization(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[IntangibleAssetEntity]:
        """Get active assets that require amortization as of a given date."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Amortization schedules
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_schedules(self, asset_id: UUID, schedules: list[dict[str, Any]]) -> None:
        """Save amortization schedules for an asset."""
        raise NotImplementedError

    @abc.abstractmethod
    async def record_amortization_schedule(
        self,
        asset_id: UUID,
        period_date: date,
        planned_amount: Decimal,
        actual_amount: Decimal,
        journal_id: UUID | None,
        period_id: UUID,
    ) -> None:
        """Record an amortization entry for a period."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Revaluation records
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def record_revaluation(
        self,
        asset_id: UUID,
        old_amount: Decimal,
        new_amount: Decimal,
        surplus: Decimal,
        date: date,
        approved_by: UUID,
    ) -> None:
        """Record a revaluation event for an asset."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Aggregate operations (if using aggregate root)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def get_aggregate_by_legal_entity(self, legal_entity_id: UUID) -> IntangibleAsset | None:
        """Get the aggregate for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def save_aggregate(self, aggregate: IntangibleAsset) -> None:
        """Save the entire aggregate."""
        raise NotImplementedError


class IntangibleAssetRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def save(self, asset: IntangibleAssetEntity) -> None: ...
    async def update(self, asset: IntangibleAssetEntity) -> None: ...
    async def get_by_id(self, asset_id: UUID) -> IntangibleAssetEntity | None: ...
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, include_inactive: bool = False
    ) -> list[IntangibleAssetEntity]: ...
    async def get_active_assets_for_amortization(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[IntangibleAssetEntity]: ...
    async def save_schedules(self, asset_id: UUID, schedules: list[dict[str, Any]]) -> None: ...
    async def record_amortization_schedule(
        self,
        asset_id: UUID,
        period_date: date,
        planned_amount: Decimal,
        actual_amount: Decimal,
        journal_id: UUID | None,
        period_id: UUID,
    ) -> None: ...
    async def record_revaluation(
        self,
        asset_id: UUID,
        old_amount: Decimal,
        new_amount: Decimal,
        surplus: Decimal,
        date: date,
        approved_by: UUID,
    ) -> None: ...
    async def get_aggregate_by_legal_entity(
        self, legal_entity_id: UUID
    ) -> IntangibleAsset | None: ...
    async def save_aggregate(self, aggregate: IntangibleAsset) -> None: ...


__all__ = [
    "IntangibleAssetRepositoryPort",
    "IntangibleAssetRepositoryPortProtocol",
]
