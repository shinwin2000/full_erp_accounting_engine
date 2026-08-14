#!/usr/bin/env python3
"""
Module: bill_of_materials_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository Bill of Materials (BOM).
    - Menyediakan implementasi in-memory untuk testing/fallback.

Defines the contract for:
- Saving and retrieving BOMs
- BOM versions
- BOM items (components)
- BOM activation and obsolescence
"""

from __future__ import annotations

import abc
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

# ==================== DOMAIN ENTITIES ====================

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


# ==================== PORT (INTERFACE) ====================

class BillOfMaterialsRepositoryPort(abc.ABC):
    """Port for BOM persistence."""

    @abc.abstractmethod
    async def save(self, bom: BillOfMaterialsEntity) -> None:
        """Save or update a BOM."""
        ...

    @abc.abstractmethod
    async def get_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        """Get BOM by ID."""
        ...

    @abc.abstractmethod
    async def get_by_code(
        self, bom_code: str, legal_entity_id: UUID
    ) -> BillOfMaterialsEntity | None:
        """Get BOM by code."""
        ...

    @abc.abstractmethod
    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None:
        """Get the active BOM for a product on a given date."""
        ...

    @abc.abstractmethod
    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None:
        """Get a specific version of BOM for a product."""
        ...

    @abc.abstractmethod
    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]:
        """List all BOM versions for a product."""
        ...

    @abc.abstractmethod
    async def get_last_bom_code(self, legal_entity_id: UUID) -> str | None:
        """Get the last used BOM code for a legal entity."""
        ...

    @abc.abstractmethod
    async def update_status(self, bom_id: UUID, new_status: str, updated_by: UUID) -> None:
        """Update the status of a BOM (activate or obsoleted)."""
        ...

    @abc.abstractmethod
    async def delete(self, bom_id: UUID) -> None:
        """Delete a BOM (only if DRAFT)."""
        ...


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


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemoryBillOfMaterialsRepository(BillOfMaterialsRepositoryPort):
    """
    Implementasi in-memory untuk repository BOM.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._boms: dict[UUID, BillOfMaterialsEntity] = {}
        self._bom_by_product: dict[UUID, list[UUID]] = {}  # product_id -> list of bom_ids
        self._lock = asyncio.Lock()

    async def save(self, bom: BillOfMaterialsEntity) -> None:
        async with self._lock:
            # Store the BOM
            self._boms[bom.id] = bom
            # Update product index
            if bom.product_id not in self._bom_by_product:
                self._bom_by_product[bom.product_id] = []
            if bom.id not in self._bom_by_product[bom.product_id]:
                self._bom_by_product[bom.product_id].append(bom.id)

    async def get_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        async with self._lock:
            return self._boms.get(bom_id)

    async def get_by_code(
        self, bom_code: str, legal_entity_id: UUID
    ) -> BillOfMaterialsEntity | None:
        async with self._lock:
            for bom in self._boms.values():
                if bom.bom_code == bom_code:
                    # Note: legal_entity_id is not stored in BOM entity,
                    # so we cannot filter by it. In a real implementation,
                    # legal_entity_id would be part of the BOM or derived from product.
                    # For in-memory testing, we just return the first match.
                    return bom
            return None

    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None:
        async with self._lock:
            bom_ids = self._bom_by_product.get(product_id, [])
            active_bom = None
            for bom_id in bom_ids:
                bom = self._boms.get(bom_id)
                if not bom:
                    continue
                if bom.status != "ACTIVE":
                    continue
                if bom.effective_date and bom.effective_date > as_of_date:
                    continue
                if bom.expiry_date and bom.expiry_date < as_of_date:
                    continue
                # Choose the one with highest version that is valid
                if not active_bom or bom.version > active_bom.version:
                    active_bom = bom
            return active_bom

    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None:
        async with self._lock:
            bom_ids = self._bom_by_product.get(product_id, [])
            for bom_id in bom_ids:
                bom = self._boms.get(bom_id)
                if bom and bom.version == version:
                    return bom
            return None

    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]:
        async with self._lock:
            bom_ids = self._bom_by_product.get(product_id, [])
            boms = [self._boms[bom_id] for bom_id in bom_ids if bom_id in self._boms]
            boms.sort(key=lambda x: x.version, reverse=True)
            return boms[offset:offset + limit]

    async def get_last_bom_code(self, legal_entity_id: UUID) -> str | None:
        async with self._lock:
            # Ignore legal_entity_id; just return the max bom_code
            codes = [bom.bom_code for bom in self._boms.values()]
            if not codes:
                return None
            codes.sort()
            return codes[-1]

    async def update_status(self, bom_id: UUID, new_status: str, updated_by: UUID) -> None:
        async with self._lock:
            bom = self._boms.get(bom_id)
            if bom:
                bom.status = new_status

    async def delete(self, bom_id: UUID) -> None:
        async with self._lock:
            bom = self._boms.get(bom_id)
            if not bom:
                return
            if bom.status != "DRAFT":
                raise ValueError("Cannot delete a BOM that is not in DRAFT status")
            # Remove from product index
            product_id = bom.product_id
            if product_id in self._bom_by_product:
                self._bom_by_product[product_id] = [bid for bid in self._bom_by_product[product_id] if bid != bom_id]
            # Remove from main storage
            del self._boms[bom_id]


# ==================== EXPORTS ====================

__all__ = [
    "BOMItem",
    "BillOfMaterialsEntity",
    "BillOfMaterialsRepositoryPort",
    "BillOfMaterialsRepositoryPortProtocol",
    "InMemoryBillOfMaterialsRepository",
]
