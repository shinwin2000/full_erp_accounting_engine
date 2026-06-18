#!/usr/bin/env python3
"""
Module: manufacturing_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port (abstract interface) for Manufacturing repository.

Defines the contract for storing and retrieving manufacturing aggregates:
- Bill of Materials (BOM)
- Work Orders
- Cost Cards
- WIP (Work in Process)
- Standard Costs

This port is implemented by adapters in adapters/secondary_impl/.

Dependencies:
- Python standard library (abc, UUID, datetime, decimal, typing)
- domain.manufacturing entities (BillOfMaterialsEntity, WorkOrderEntity, etc.)

Audit: This is a port, no direct audit logging here.
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

# Import domain entities (required for interface signatures)
from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity
from domain.manufacturing.cost_card_entity import CostCardEntity
from domain.manufacturing.standard_cost_entity import StandardCostEntity
from domain.manufacturing.work_in_process_entity import WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus

# ============================================================================
# Manufacturing Repository Port (Abstract Base Class)
# ============================================================================


class ManufacturingRepositoryPort(abc.ABC):
    """
    Port (interface) for manufacturing repository operations.
    All methods must be implemented by concrete adapters.
    """

    # ------------------------------------------------------------------------
    # Bill of Materials (BOM) operations
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def save_bom(self, bom: BillOfMaterialsEntity) -> None:
        """Save or update a Bill of Materials."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_bom_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        """Retrieve a BOM by its ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None:
        """
        Retrieve the active BOM for a product on a given date.
        Active means status=ACTIVE and effective_date <= as_of_date <= expiry_date.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None:
        """Retrieve a specific version of BOM for a product."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]:
        """List all BOM versions for a product."""
        raise NotImplementedError

    # ------------------------------------------------------------------------
    # Work Order operations
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def save_work_order(self, work_order: WorkOrderEntity) -> None:
        """Save or update a work order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_work_order(self, work_order_id: UUID) -> WorkOrderEntity | None:
        """Retrieve a work order by its ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_work_order_by_number(self, work_order_number: str) -> WorkOrderEntity | None:
        """Retrieve a work order by its human-readable number."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_work_orders_by_product(
        self,
        product_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        status: WorkOrderStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkOrderEntity]:
        """List work orders for a product with optional filters."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_completed_work_orders(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[WorkOrderEntity]:
        """List work orders completed within the date range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_work_order_number(self) -> str | None:
        """Return the last used work order number (for generating next sequence)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def count_work_orders_by_status(
        self, status: WorkOrderStatus, legal_entity_id: UUID
    ) -> int:
        """Count work orders with a given status."""
        raise NotImplementedError

    # ------------------------------------------------------------------------
    # Work in Process (WIP) operations
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def save_wip(self, wip: WorkInProcessEntity) -> None:
        """Save or update a WIP record."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_wip_by_work_order(self, work_order_id: UUID) -> WorkInProcessEntity | None:
        """Retrieve WIP record for a specific work order."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_open_wip(self, legal_entity_id: UUID) -> list[WorkInProcessEntity]:
        """List all open WIP records."""
        raise NotImplementedError

    # ------------------------------------------------------------------------
    # Cost Card operations
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def save_cost_card(self, cost_card: CostCardEntity) -> None:
        """Save or update a cost card."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_cost_card(self, product_id: UUID, period: str) -> CostCardEntity | None:
        """
        Retrieve cost card for a product and period (format: YYYY-MM).
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_cost_card_by_id(self, cost_card_id: UUID) -> CostCardEntity | None:
        """Retrieve cost card by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_cost_cards_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CostCardEntity]:
        """List cost cards for a product."""
        raise NotImplementedError

    # ------------------------------------------------------------------------
    # Standard Cost operations
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def save_standard_cost(self, standard_cost: StandardCostEntity) -> None:
        """Save or update a standard cost record."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_standard_cost_by_product(
        self, product_id: UUID, as_of_date: datetime | None = None
    ) -> StandardCostEntity | None:
        """
        Retrieve the active standard cost for a product as of a given date.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_standard_cost_by_id(self, standard_cost_id: UUID) -> StandardCostEntity | None:
        """Retrieve standard cost by ID."""
        raise NotImplementedError

    # ------------------------------------------------------------------------
    # Period operations
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def close_period(self, legal_entity_id: UUID, period: str, user_id: UUID) -> None:
        """
        Close a manufacturing period (prevent further changes).
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def is_period_closed(self, legal_entity_id: UUID, period: str) -> bool:
        """Check if a period is closed."""
        raise NotImplementedError

    # ------------------------------------------------------------------------
    # Batch operations (for performance)
    # ------------------------------------------------------------------------

    @abc.abstractmethod
    async def save_bom_batch(self, boms: list[BillOfMaterialsEntity]) -> None:
        """Save multiple BOMs in a batch."""
        raise NotImplementedError

    @abc.abstractmethod
    async def save_work_order_batch(self, work_orders: list[WorkOrderEntity]) -> None:
        """Save multiple work orders in a batch."""
        raise NotImplementedError


# ============================================================================
# Alternative Protocol-based port (for structural subtyping)
# ============================================================================


class ManufacturingRepositoryPortProtocol(Protocol):
    """
    Protocol version of ManufacturingRepositoryPort for static duck typing.
    """

    async def save_bom(self, bom: BillOfMaterialsEntity) -> None: ...
    async def get_bom_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None: ...
    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None: ...
    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None: ...
    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]: ...

    async def save_work_order(self, work_order: WorkOrderEntity) -> None: ...
    async def get_work_order(self, work_order_id: UUID) -> WorkOrderEntity | None: ...
    async def get_work_order_by_number(self, work_order_number: str) -> WorkOrderEntity | None: ...
    async def list_work_orders_by_product(
        self,
        product_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        status: WorkOrderStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkOrderEntity]: ...
    async def list_completed_work_orders(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]: ...
    async def get_last_work_order_number(self) -> str | None: ...
    async def count_work_orders_by_status(
        self, status: WorkOrderStatus, legal_entity_id: UUID
    ) -> int: ...

    async def save_wip(self, wip: WorkInProcessEntity) -> None: ...
    async def get_wip_by_work_order(self, work_order_id: UUID) -> WorkInProcessEntity | None: ...
    async def list_open_wip(self, legal_entity_id: UUID) -> list[WorkInProcessEntity]: ...

    async def save_cost_card(self, cost_card: CostCardEntity) -> None: ...
    async def get_cost_card(self, product_id: UUID, period: str) -> CostCardEntity | None: ...
    async def get_cost_card_by_id(self, cost_card_id: UUID) -> CostCardEntity | None: ...
    async def list_cost_cards_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CostCardEntity]: ...

    async def save_standard_cost(self, standard_cost: StandardCostEntity) -> None: ...
    async def get_standard_cost_by_product(
        self, product_id: UUID, as_of_date: datetime | None = None
    ) -> StandardCostEntity | None: ...
    async def get_standard_cost_by_id(
        self, standard_cost_id: UUID
    ) -> StandardCostEntity | None: ...

    async def close_period(self, legal_entity_id: UUID, period: str, user_id: UUID) -> None: ...
    async def is_period_closed(self, legal_entity_id: UUID, period: str) -> bool: ...

    async def save_bom_batch(self, boms: list[BillOfMaterialsEntity]) -> None: ...
    async def save_work_order_batch(self, work_orders: list[WorkOrderEntity]) -> None: ...


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ManufacturingRepositoryPort",
    "ManufacturingRepositoryPortProtocol",
]
