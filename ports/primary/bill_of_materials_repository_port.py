#!/usr/bin/env python3
"""
Module: bill_of_materials_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for Bill of Materials (BOM) repository operations.

Defines the contract for:
- Saving and retrieving BOMs
- BOM versions
- BOM items (components)
- BOM activation and obsolescence
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


class BOMItem:
    """Represents a component in a BOM."""

    def __init__(
        self,
        component_id: UUID,
        component_code: str,
        component_name: str,
        quantity: Decimal,
        unit_of_measure: str,
        scrap_percentage: Decimal = Decimal("0"),
        sub_bom_id: UUID | None = None,
        notes: str = "",
    ):
        self.component_id = component_id
        self.component_code = component_code
        self.component_name = component_name
        self.quantity = quantity
        self.unit_of_measure = unit_of_measure
        self.scrap_percentage = scrap_percentage
        self.sub_bom_id = sub_bom_id
        self.notes = notes


class BillOfMaterialsEntity:
    """Represents a Bill of Materials."""

    def __init__(
        self,
        id: UUID,
        bom_code: str,
        product_id: UUID,
        product_code: str,
        product_name: str,
        version: int,
        quantity_per_assembly: Decimal,
        unit_of_measure: str,
        items: list[BOMItem],
        status: str,  # DRAFT, ACTIVE, OBSOLETE
        effective_date: date | None = None,
        expiry_date: date | None = None,
        notes: str = "",
        created_by: UUID | None = None,
        created_at: datetime | None = None,
        version_counter: int = 1,
    ):
        self.id = id
        self.bom_code = bom_code
        self.product_id = product_id
        self.product_code = product_code
        self.product_name = product_name
        self.version = version
        self.quantity_per_assembly = quantity_per_assembly
        self.unit_of_measure = unit_of_measure
        self.items = items
        self.status = status
        self.effective_date = effective_date
        self.expiry_date = expiry_date
        self.notes = notes
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()
        self.version_counter = version_counter


class BillOfMaterialsRepositoryPort(abc.ABC):
    """Port for BOM persistence."""

    @abc.abstractmethod
    async def save(self, bom: BillOfMaterialsEntity) -> None:
        """Save or update a BOM."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        """Get BOM by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_by_code(
        self, bom_code: str, legal_entity_id: UUID
    ) -> BillOfMaterialsEntity | None:
        """Get BOM by code."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None:
        """Get the active BOM for a product on a given date."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None:
        """Get a specific version of BOM for a product."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]:
        """List all BOM versions for a product."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_bom_code(self, legal_entity_id: UUID) -> str | None:
        """Get the last used BOM code for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(self, bom_id: UUID, new_status: str, updated_by: UUID) -> None:
        """Update the status of a BOM (activate or obsoleted)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete(self, bom_id: UUID) -> None:
        """Delete a BOM (only if DRAFT)."""
        raise NotImplementedError


class BillOfMaterialsRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def save(self, bom: BillOfMaterialsEntity) -> None: ...
    async def get_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None: ...
    async def get_by_code(
        self, bom_code: str, legal_entity_id: UUID
    ) -> BillOfMaterialsEntity | None: ...
    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None: ...
    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None: ...
    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]: ...
    async def get_last_bom_code(self, legal_entity_id: UUID) -> str | None: ...
    async def update_status(self, bom_id: UUID, new_status: str, updated_by: UUID) -> None: ...
    async def delete(self, bom_id: UUID) -> None: ...


__all__ = [
    "BOMItem",
    "BillOfMaterialsEntity",
    "BillOfMaterialsRepositoryPort",
    "BillOfMaterialsRepositoryPortProtocol",
]
