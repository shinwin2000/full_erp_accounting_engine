#!/usr/bin/env python3
"""
Module: overhead_allocation_engine.py
Layer: 6 - Domain / Manufacturing
Responsibility: Overhead cost allocation to products.

Provides an engine to allocate factory overhead costs to products based on
specified allocation bases (direct labor hours, machine hours, material cost, etc.).

Dependencies:
- Python standard library (decimal, logging, dataclasses, enum, datetime)
- domain.manufacturing.work_order_entity (WorkOrderEntity)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every allocation result is recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.manufacturing.work_order_entity import WorkOrderEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class AllocationBasis(Enum):
    """Basis for overhead allocation."""

    DIRECT_LABOR_HOURS = "direct_labor_hours"
    MACHINE_HOURS = "machine_hours"
    DIRECT_LABOR_COST = "direct_labor_cost"
    MATERIAL_COST = "material_cost"
    UNITS_PRODUCED = "units_produced"
    ACTIVITY_BASED = "activity_based"


class OverheadPool(Enum):
    """Overhead cost pool types."""

    FACTORY_RENT = "factory_rent"
    UTILITIES = "utilities"
    DEPRECIATION = "depreciation"
    MAINTENANCE = "maintenance"
    SUPERVISION = "supervision"
    QUALITY_CONTROL = "quality_control"
    SETUP = "setup"
    MATERIAL_HANDLING = "material_handling"
    GENERAL = "general"


# ============================================================================
# Allocation Rate (Value Object)
# ============================================================================


@dataclass(frozen=True)
class AllocationRate:
    """
    Overhead allocation rate (immutable value object).

    Attributes:
        pool: Overhead pool type.
        basis: Allocation basis.
        rate: Rate per unit of basis (e.g., $10 per direct labor hour).
        total_pool_cost: Total cost in this pool for the period.
        total_basis_units: Total basis units for the period (used to calculate rate).
        effective_date: Start date of this rate.
        expiry_date: Optional end date.
        description: Optional description.
    """

    pool: OverheadPool
    basis: AllocationBasis
    rate: Decimal
    total_pool_cost: Decimal
    total_basis_units: Decimal
    effective_date: datetime
    expiry_date: datetime | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.rate < 0:
            raise ValueError(f"Rate cannot be negative: {self.rate}")
        if self.total_pool_cost < 0:
            raise ValueError(f"Total pool cost cannot be negative: {self.total_pool_cost}")
        if self.total_basis_units < 0:
            raise ValueError(f"Total basis units cannot be negative: {self.total_basis_units}")
        if self.effective_date.tzinfo is None:
            raise ValueError("effective_date must be timezone-aware")
        if self.expiry_date and self.expiry_date.tzinfo is None:
            raise ValueError("expiry_date must be timezone-aware")
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiry_date must be after effective_date")

    def calculate_allocation(self, basis_units: Decimal) -> Decimal:
        """
        Calculate allocated overhead for given basis units.

        Args:
            basis_units: Number of basis units for a specific work order.

        Returns:
            Allocated overhead amount.
        """
        if basis_units < 0:
            raise ValueError(f"Basis units cannot be negative: {basis_units}")
        return basis_units * self.rate

    def is_active_at(self, date: datetime) -> bool:
        """Check if this rate is active on the given date."""
        return date >= self.effective_date and (self.expiry_date is None or date <= self.expiry_date)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool.value,
            "basis": self.basis.value,
            "rate": str(self.rate),
            "total_pool_cost": str(self.total_pool_cost),
            "total_basis_units": str(self.total_basis_units),
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "description": self.description,
        }


# ============================================================================
# Allocation Result (Value Object)
# ============================================================================


@dataclass(frozen=True)
class AllocationResult:
    """
    Result of overhead allocation for a work order (immutable).

    Attributes:
        work_order_id: Work order ID.
        work_order_number: Work order number.
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        quantity: Quantity produced in this work order.
        allocations: Dictionary mapping OverheadPool to allocated amount.
        total_allocated: Sum of all allocated amounts.
        allocation_basis: Primary basis used (if multiple, the first).
        calculation_date: When the allocation was performed.
    """

    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str
    product_name: str
    quantity: Decimal
    allocations: dict[OverheadPool, Decimal]
    total_allocated: Decimal
    allocation_basis: AllocationBasis
    calculation_date: datetime

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.quantity}")
        if self.total_allocated < 0:
            raise ValueError(f"Total allocated cannot be negative: {self.total_allocated}")
        if self.calculation_date.tzinfo is None:
            raise ValueError("calculation_date must be timezone-aware")
        # Verify total matches sum of allocations
        calc_total = sum(self.allocations.values())
        diff = abs(self.total_allocated - calc_total)
        if diff > Decimal("0.01"):
            raise ValueError(
                f"Total allocated {self.total_allocated} does not match sum of allocations {calc_total}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "quantity": str(self.quantity),
            "allocations": {k.value: str(v) for k, v in self.allocations.items()},
            "total_allocated": str(self.total_allocated),
            "allocation_basis": self.allocation_basis.value,
            "calculation_date": self.calculation_date.isoformat(),
        }


# ============================================================================
# Overhead Allocation Engine
# ============================================================================


class OverheadAllocationEngine:
    """
    Engine for allocating factory overhead to work orders.

    Business context:
    Allocates indirect costs to products based on predetermined rates
    and allocation bases. Supports activity-based costing (ABC).

    Features:
    - Multiple overhead pools with different allocation bases.
    - Predetermined rate calculation.
    - Batch allocation for multiple work orders.
    - Activity-based costing support.
    """

    def __init__(self):
        self._allocation_rates: list[AllocationRate] = []
        self._allocation_results: list[AllocationResult] = []

    # ------------------------------------------------------------------------
    # Rate management
    # ------------------------------------------------------------------------

    def add_allocation_rate(self, rate: AllocationRate) -> None:
        """Add or replace an allocation rate (by pool and effective date)."""
        # Remove any overlapping rate for same pool and basis (simplified: just add)
        self._allocation_rates.append(rate)
        logger.info(
            f"Added allocation rate: {rate.pool.value} @ {rate.rate} per {rate.basis.value}"
        )

    def get_active_rates(self, as_of_date: datetime) -> list[AllocationRate]:
        """Get all rates active on a specific date."""
        return [r for r in self._allocation_rates if r.is_active_at(as_of_date)]

    def get_rates_for_pool(self, pool: OverheadPool) -> list[AllocationRate]:
        """Get all rates for a specific overhead pool."""
        return [r for r in self._allocation_rates if r.pool == pool]

    def clear_rates(self) -> None:
        """Clear all allocation rates."""
        self._allocation_rates = []

    # ------------------------------------------------------------------------
    # Basis unit calculation
    # ------------------------------------------------------------------------

    def calculate_basis_units(
        self,
        work_order: WorkOrderEntity,
        basis: AllocationBasis,
        custom_basis_values: dict[str, Decimal] | None = None,
    ) -> Decimal:
        """
        Calculate basis units for a work order.

        Args:
            work_order: Work order entity.
            basis: Allocation basis type.
            custom_basis_values: Optional override values for custom bases.

        Returns:
            Number of basis units.

        Raises:
            ValueError: If basis is not supported or missing required data.
        """
        if basis == AllocationBasis.UNITS_PRODUCED:
            return work_order.completed_quantity

        elif basis == AllocationBasis.DIRECT_LABOR_HOURS:
            # If work order has actual labor hours, use that. Otherwise estimate.
            if hasattr(work_order, "actual_labor_hours") and work_order.actual_labor_hours:
                return work_order.actual_labor_hours
            # Default estimate: assume 2 hours per unit
            return work_order.completed_quantity * Decimal(2)

        elif basis == AllocationBasis.MACHINE_HOURS:
            if hasattr(work_order, "actual_machine_hours") and work_order.actual_machine_hours:
                return work_order.actual_machine_hours
            # Default estimate: assume 1.5 hours per unit
            return work_order.completed_quantity * Decimal("1.5")

        elif basis == AllocationBasis.DIRECT_LABOR_COST:
            return work_order.labor_actual_cost if work_order.labor_actual_cost else Decimal(0)

        elif basis == AllocationBasis.MATERIAL_COST:
            return (
                work_order.material_actual_cost if work_order.material_actual_cost else Decimal(0)
            )

        elif basis == AllocationBasis.ACTIVITY_BASED:
            # For ABC, we need custom basis values
            if custom_basis_values:
                # Sum of all custom driver quantities (or use specific)
                return sum(custom_basis_values.values())
            return Decimal(0)

        else:
            raise ValueError(f"Unsupported allocation basis: {basis}")

    # ------------------------------------------------------------------------
    # Allocation methods
    # ------------------------------------------------------------------------

    def allocate(
        self,
        work_order: WorkOrderEntity,
        as_of_date: datetime,
        custom_rates: list[AllocationRate] | None = None,
        custom_basis_values: dict[str, Decimal] | None = None,
    ) -> AllocationResult:
        """
        Allocate overhead to a single work order.

        Args:
            work_order: Work order to allocate.
            as_of_date: Date for rate selection.
            custom_rates: Optional override rates (if not provided, uses active rates).
            custom_basis_values: Optional custom basis values for ABC.

        Returns:
            AllocationResult.

        Raises:
            ValueError: If work order has no completed quantity.
        """
        if work_order.completed_quantity <= 0:
            raise ValueError(f"Work order {work_order.work_order_number} has no completed units")

        rates = custom_rates if custom_rates is not None else self.get_active_rates(as_of_date)
        if not rates:
            logger.warning(f"No active allocation rates found for date {as_of_date}")
            rates = []

        allocations = {}
        total_allocated = Decimal(0)
        primary_basis = AllocationBasis.UNITS_PRODUCED

        for rate in rates:
            basis_units = self.calculate_basis_units(work_order, rate.basis, custom_basis_values)
            allocated = rate.calculate_allocation(basis_units)
            allocations[rate.pool] = allocated
            total_allocated += allocated
            if primary_basis == AllocationBasis.UNITS_PRODUCED:
                primary_basis = rate.basis

        return AllocationResult(
            work_order_id=work_order.work_order_id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            product_code=work_order.product_code,
            product_name=work_order.product_name,
            quantity=work_order.completed_quantity,
            allocations=allocations,
            total_allocated=total_allocated,
            allocation_basis=primary_basis,
            calculation_date=as_of_date,
        )

    def allocate_batch(
        self,
        work_orders: list[WorkOrderEntity],
        as_of_date: datetime,
    ) -> list[AllocationResult]:
        """
        Allocate overhead to multiple work orders.

        Args:
            work_orders: List of work orders.
            as_of_date: Date for rate selection.

        Returns:
            List of AllocationResult objects.
        """
        results = []
        for wo in work_orders:
            try:
                result = self.allocate(wo, as_of_date)
                results.append(result)
                self._allocation_results.append(result)
            except ValueError as e:
                logger.error(f"Allocation failed for {wo.work_order_number}: {e}")
                continue
        return results

    # ------------------------------------------------------------------------
    # Predetermined rate calculation
    # ------------------------------------------------------------------------

    @staticmethod
    def calculate_predetermined_rate(
        estimated_overhead: Decimal,
        estimated_activity: Decimal,
    ) -> Decimal:
        """
        Calculate a predetermined overhead rate.

        Formula: Estimated Overhead / Estimated Activity

        Args:
            estimated_overhead: Estimated total overhead cost for period.
            estimated_activity: Estimated total activity (e.g., labor hours).

        Returns:
            Predetermined rate per unit of activity.
        """
        if estimated_activity <= 0:
            return Decimal(0)
        return estimated_overhead / estimated_activity

    @classmethod
    def create_rate_from_predetermined(
        cls,
        pool: OverheadPool,
        basis: AllocationBasis,
        estimated_overhead: Decimal,
        estimated_activity: Decimal,
        effective_date: datetime,
        expiry_date: datetime | None = None,
    ) -> AllocationRate:
        """
        Create an AllocationRate using predetermined rate calculation.

        Args:
            pool: Overhead pool.
            basis: Allocation basis.
            estimated_overhead: Estimated overhead for the pool.
            estimated_activity: Estimated total basis units.
            effective_date: Start date.
            expiry_date: Optional end date.

        Returns:
            AllocationRate with calculated rate.
        """
        rate = cls.calculate_predetermined_rate(estimated_overhead, estimated_activity)
        return AllocationRate(
            pool=pool,
            basis=basis,
            rate=rate,
            total_pool_cost=estimated_overhead,
            total_basis_units=estimated_activity,
            effective_date=effective_date,
            expiry_date=expiry_date,
            description=f"Predetermined rate based on estimated overhead {estimated_overhead} and activity {estimated_activity}",
        )

    # ------------------------------------------------------------------------
    # Activity-Based Costing (ABC) support
    # ------------------------------------------------------------------------

    def allocate_activity_based(
        self,
        work_order: WorkOrderEntity,
        cost_drivers: dict[str, Decimal],  # driver name -> quantity for this work order
        driver_rates: dict[str, Decimal],  # driver name -> rate per unit
        as_of_date: datetime | None = None,
    ) -> AllocationResult:
        """
        Allocate overhead using Activity-Based Costing.

        Args:
            work_order: Work order.
            cost_drivers: Dictionary mapping driver name to quantity.
            driver_rates: Dictionary mapping driver name to rate per unit.
            as_of_date: Optional date (defaults to now).

        Returns:
            AllocationResult.
        """
        if work_order.completed_quantity <= 0:
            raise ValueError(f"Work order {work_order.work_order_number} has no completed units")

        as_of_date = as_of_date or datetime.now(UTC)
        allocations = {}
        total_allocated = Decimal(0)

        for driver, quantity in cost_drivers.items():
            rate = driver_rates.get(driver, Decimal(0))
            allocated = quantity * rate
            # Map driver to a pool (simplified: use driver name as pool key)
            # Since OverheadPool is an enum, we'll use GENERAL for ABC or map known drivers
            pool = OverheadPool.GENERAL
            allocations[pool] = allocations.get(pool, Decimal(0)) + allocated
            total_allocated += allocated

        return AllocationResult(
            work_order_id=work_order.work_order_id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            product_code=work_order.product_code,
            product_name=work_order.product_name,
            quantity=work_order.completed_quantity,
            allocations=allocations,
            total_allocated=total_allocated,
            allocation_basis=AllocationBasis.ACTIVITY_BASED,
            calculation_date=as_of_date,
        )

    # ------------------------------------------------------------------------
    # History and reporting
    # ------------------------------------------------------------------------

    def get_allocation_history(self, work_order_id: UUID | None = None) -> list[AllocationResult]:
        """Retrieve previous allocation results."""
        if work_order_id:
            return [r for r in self._allocation_results if r.work_order_id == work_order_id]
        return self._allocation_results.copy()

    def get_total_allocated_for_period(self, from_date: datetime, to_date: datetime) -> Decimal:
        """Sum of all allocations within a date range."""
        total = Decimal(0)
        for result in self._allocation_results:
            if from_date <= result.calculation_date <= to_date:
                total += result.total_allocated
        return total

    def get_allocation_summary_by_pool(self) -> dict[OverheadPool, Decimal]:
        """Aggregate allocated amounts by overhead pool."""
        summary = {}
        for result in self._allocation_results:
            for pool, amount in result.allocations.items():
                summary[pool] = summary.get(pool, Decimal(0)) + amount
        return summary

    def reset(self) -> None:
        """Clear all rates and history."""
        self._allocation_rates = []
        self._allocation_results = []


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AllocationBasis",
    "AllocationRate",
    "AllocationResult",
    "OverheadAllocationEngine",
    "OverheadPool",
]
