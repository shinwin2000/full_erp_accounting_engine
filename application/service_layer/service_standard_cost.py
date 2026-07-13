# service_standard_cost.py - Complete service for Standard Cost management

#!/usr/bin/env python3

"""
Module: service_standard_cost.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola standard cost produk.
    Mempublikasikan StandardCostCreatedEvent dan StandardCostActivatedEvent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

# Import domain events
from application.events import StandardCostActivatedEvent, StandardCostCreatedEvent
from ports.primary.event_publisher_port import EventPublisherPort

logger = logging.getLogger(__name__)


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class StandardCost:
    id: UUID = field(default_factory=uuid4)
    product_id: UUID
    product_code: str
    product_name: str
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    effective_date: date
    is_active: bool = False
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class StandardCostServiceError(Exception):
    pass


class StandardCostNotFoundError(StandardCostServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class StandardCostService:
    """
    Service untuk mengelola standard cost.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._costs: dict[UUID, StandardCost] = {}
        self._event_publisher = event_publisher
        self._stats = {"costs_created": 0, "costs_activated": 0}

        logger.info("StandardCostService initialized")

    async def create_standard_cost(
        self,
        product_id: UUID,
        product_code: str,
        product_name: str,
        material_cost: Decimal,
        labor_cost: Decimal,
        overhead_cost: Decimal,
        effective_date: date,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> StandardCost:
        """Create a new standard cost."""
        total_cost = material_cost + labor_cost + overhead_cost

        cost = StandardCost(
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            material_cost=material_cost,
            labor_cost=labor_cost,
            overhead_cost=overhead_cost,
            total_cost=total_cost,
            effective_date=effective_date,
            created_by=created_by,
            version=1,
        )

        self._costs[cost.id] = cost
        self._stats["costs_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = StandardCostCreatedEvent(
                    aggregate_id=cost.id,
                    aggregate_version=cost.version,
                    standard_cost_id=cost.id,
                    product_id=cost.product_id,
                    product_code=cost.product_code,
                    product_name=cost.product_name,
                    material_cost=cost.material_cost,
                    labor_cost=cost.labor_cost,
                    overhead_cost=cost.overhead_cost,
                    total_cost=cost.total_cost,
                    effective_date=datetime.combine(cost.effective_date, datetime.min.time()),
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published StandardCostCreatedEvent for {product_code}")
            except Exception as e:
                logger.warning(f"Failed to publish StandardCostCreatedEvent: {e}")

        logger.info(f"Standard cost created for {product_code}: {total_cost}")
        return cost

    async def activate_standard_cost(
        self,
        standard_cost_id: UUID,
        activated_by: UUID,
        correlation_id: str | None = None,
    ) -> StandardCost:
        """Activate a standard cost."""
        cost = self._costs.get(standard_cost_id)
        if not cost:
            raise StandardCostNotFoundError(f"Standard cost {standard_cost_id} not found")

        # Deactivate other standard costs for same product
        for c in self._costs.values():
            if c.product_id == cost.product_id and c.id != cost.id:
                c.is_active = False
                c.updated_at = datetime.now(UTC)
                c.version += 1

        cost.is_active = True
        cost.updated_at = datetime.now(UTC)
        cost.version += 1
        self._costs[standard_cost_id] = cost
        self._stats["costs_activated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = StandardCostActivatedEvent(
                    aggregate_id=cost.id,
                    aggregate_version=cost.version,
                    standard_cost_id=cost.id,
                    product_id=cost.product_id,
                    product_code=cost.product_code,
                    product_name=cost.product_name,
                    activated_by=str(activated_by),
                    user_id=str(activated_by),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published StandardCostActivatedEvent for {cost.product_code}")
            except Exception as e:
                logger.warning(f"Failed to publish StandardCostActivatedEvent: {e}")

        logger.info(f"Standard cost activated for {cost.product_code}")
        return cost

    async def get_active_standard_cost(self, product_id: UUID) -> StandardCost | None:
        """Get active standard cost for a product."""
        for cost in self._costs.values():
            if cost.product_id == product_id and cost.is_active:
                return cost
        return None

    async def get_standard_cost(self, standard_cost_id: UUID) -> StandardCost | None:
        return self._costs.get(standard_cost_id)

    async def list_standard_costs(self, product_id: UUID | None = None) -> list[StandardCost]:
        if product_id:
            return [c for c in self._costs.values() if c.product_id == product_id]
        return list(self._costs.values())

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_standard_cost_service(
    event_publisher: EventPublisherPort | None = None,
) -> StandardCostService:
    return StandardCostService(event_publisher=event_publisher)


__all__ = [
    "StandardCost",
    "StandardCostNotFoundError",
    "StandardCostService",
    "StandardCostServiceError",
    "create_standard_cost_service",
]
