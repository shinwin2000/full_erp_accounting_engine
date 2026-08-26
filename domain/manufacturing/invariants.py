#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Manufacturing
Responsibility: Business invariants: stock non-negative, BOM valid, etc.

Defines all invariants that must be satisfied by the Manufacturing aggregate.
Ensures production data is always in a valid business state.

Dependencies:
- Python standard library (logging, datetime, decimal, typing)
- domain.manufacturing.work_order_entity (WorkOrderEntity, WorkOrderStatus)
- domain.manufacturing.bill_of_materials_entity (BillOfMaterialsEntity, BOMStatus)
- domain.manufacturing.work_in_process_entity (WorkInProcessEntity)

Audit: Every invariant violation is logged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus
from domain.manufacturing.work_in_process_entity import WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Validation Result
# ============================================================================


class InvariantResult:
    """
    Result of invariant validation.

    Attributes:
        is_valid: True if all invariants passed.
        errors: List of error messages.
    """

    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        """Add an error message and mark as invalid."""
        self.errors.append(error)
        self.is_valid = False
        logger.warning(f"Invariant violation: {error}")

    def merge(self, other: InvariantResult) -> InvariantResult:
        """Merge another result into this one."""
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "error_count": len(self.errors),
        }

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        return f"InvariantResult(is_valid={self.is_valid}, errors={self.errors})"


# ============================================================================
# Manufacturing Invariants (Static Methods)
# ============================================================================


class ManufacturingInvariants:
    """
    Collection of static invariant validation methods.

    Each method validates a specific business rule and returns an
    InvariantResult. These methods are pure (no side effects) and
    can be used independently.
    """

    # ------------------------------------------------------------------------
    # Work Order Invariants
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_work_order_quantity(work_order: WorkOrderEntity) -> InvariantResult:
        """
        Invariant: Planned quantity must be positive.

        Args:
            work_order: The work order to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)
        if work_order.planned_quantity <= 0:
            result.add_error(
                f"Work order {work_order.work_order_number} planned quantity must be positive: {work_order.planned_quantity}"
            )
        return result

    @staticmethod
    def validate_completed_quantity(work_order: WorkOrderEntity) -> InvariantResult:
        """
        Invariant: Completed quantity cannot exceed planned quantity.

        Args:
            work_order: The work order to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)
        if work_order.completed_quantity > work_order.planned_quantity:
            result.add_error(
                f"Work order {work_order.work_order_number} completed quantity {work_order.completed_quantity} "
                f"exceeds planned quantity {work_order.planned_quantity}"
            )
        return result

    @staticmethod
    def validate_work_order_status_transition(
        current_status: WorkOrderStatus,
        new_status: WorkOrderStatus,
    ) -> InvariantResult:
        """
        Invariant: Status transitions must follow allowed paths.

        Valid transitions:
            DRAFT -> APPROVED, CANCELLED
            APPROVED -> IN_PROGRESS, CANCELLED
            IN_PROGRESS -> COMPLETED, PARTIALLY_COMPLETED, CANCELLED
            PARTIALLY_COMPLETED -> IN_PROGRESS, COMPLETED, CANCELLED
            COMPLETED -> (none)
            CANCELLED -> (none)

        Args:
            current_status: Current status.
            new_status: Desired new status.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        valid_transitions = {
            WorkOrderStatus.DRAFT: [WorkOrderStatus.APPROVED, WorkOrderStatus.CANCELLED],
            WorkOrderStatus.APPROVED: [WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED],
            WorkOrderStatus.IN_PROGRESS: [
                WorkOrderStatus.COMPLETED,
                WorkOrderStatus.PARTIALLY_COMPLETED,
                WorkOrderStatus.CANCELLED,
            ],
            WorkOrderStatus.PARTIALLY_COMPLETED: [
                WorkOrderStatus.IN_PROGRESS,
                WorkOrderStatus.COMPLETED,
                WorkOrderStatus.CANCELLED,
            ],
            WorkOrderStatus.COMPLETED: [],
            WorkOrderStatus.CANCELLED: [],
        }

        allowed = valid_transitions.get(current_status, [])
        if new_status not in allowed:
            result.add_error(
                f"Invalid status transition from {current_status.value} to {new_status.value}"
            )
        return result

    @staticmethod
    def validate_work_order_dates(work_order: WorkOrderEntity) -> InvariantResult:
        """
        Invariant: Planned end date must be after planned start date.
                   Actual dates must be consistent if present.

        Args:
            work_order: The work order to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if work_order.planned_end_date <= work_order.planned_start_date:
            result.add_error(
                f"Work order {work_order.work_order_number}: planned end date {work_order.planned_end_date} "
                f"must be after planned start date {work_order.planned_start_date}"
            )

        # Combined condition for actual dates
        if (
            work_order.actual_start_date
            and work_order.actual_end_date
            and work_order.actual_end_date < work_order.actual_start_date
        ):
            result.add_error(
                f"Work order {work_order.work_order_number}: actual end date {work_order.actual_end_date} "
                f"cannot be before actual start date {work_order.actual_start_date}"
            )

        # Note: actual_start_date before planned_start_date is allowed (might be a warning)
        # We intentionally do nothing for that case.

        return result

    # ------------------------------------------------------------------------
    # BOM Invariants
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_bom_structure(bom: BillOfMaterialsEntity) -> InvariantResult:
        """
        Invariant: BOM must have at least one component and no circular references.

        Args:
            bom: The BOM to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if not bom.items:
            result.add_error(f"BOM {bom.bom_code} must have at least one component")

        # Check for self-reference (circular)
        for item in bom.items:
            if item.sub_bom_id == bom.bom_id:
                result.add_error(f"BOM {bom.bom_code} has circular reference to itself")

        # Check for duplicate item codes within the same BOM
        item_codes = [item.item_code for item in bom.items]
        if len(item_codes) != len(set(item_codes)):
            duplicates = {code for code in item_codes if item_codes.count(code) > 1}
            result.add_error(f"BOM {bom.bom_code} has duplicate item codes: {duplicates}")

        # Check for zero or negative quantities
        for item in bom.items:
            if item.quantity <= 0:
                result.add_error(
                    f"BOM {bom.bom_code} item {item.item_code} has non-positive quantity: {item.quantity}"
                )

        return result

    @staticmethod
    def validate_bom_effective_date(bom: BillOfMaterialsEntity, date: datetime) -> InvariantResult:
        """
        Invariant: BOM must be active on the given date.

        Args:
            bom: The BOM to validate.
            date: The date to check.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if bom.status != BOMStatus.ACTIVE:
            result.add_error(f"BOM {bom.bom_code} is not active (status: {bom.status.value})")

        if bom.effective_date and date < bom.effective_date:
            result.add_error(
                f"BOM {bom.bom_code} effective date {bom.effective_date.date()} is after {date.date()}"
            )

        if bom.expiry_date and date > bom.expiry_date:
            result.add_error(f"BOM {bom.bom_code} expired on {bom.expiry_date.date()}")

        return result

    @staticmethod
    def validate_bom_version_continuity(
        previous_bom: BillOfMaterialsEntity | None,
        new_bom: BillOfMaterialsEntity,
    ) -> InvariantResult:
        """
        Invariant: New BOM version must have higher version number and same product.

        Args:
            previous_bom: Previous version (if any).
            new_bom: New version to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if previous_bom:
            if new_bom.product_id != previous_bom.product_id:
                result.add_error(
                    f"New BOM product {new_bom.product_id} does not match previous product {previous_bom.product_id}"
                )
            if new_bom.version <= previous_bom.version:
                result.add_error(
                    f"New BOM version {new_bom.version} must be greater than previous version {previous_bom.version}"
                )

        return result

    # ------------------------------------------------------------------------
    # WIP Invariants
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_wip_consistency(wip: WorkInProcessEntity) -> InvariantResult:
        """
        Invariant: WIP must have consistent quantities and non-negative costs.

        Rules:
            - quantity_started > 0
            - quantity_remaining >= 0
            - quantity_started = quantity_remaining + quantity_completed
            - total_cost >= 0
            - total_cost = material_cost + labor_cost + overhead_cost

        Args:
            wip: The WIP entity to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if wip.quantity_started <= 0:
            result.add_error(
                f"WIP for work order {wip.work_order_number} has non-positive quantity started: {wip.quantity_started}"
            )

        if wip.quantity_remaining < 0:
            result.add_error(
                f"WIP for work order {wip.work_order_number} has negative quantity remaining: {wip.quantity_remaining}"
            )

        if wip.quantity_completed < 0:
            result.add_error(
                f"WIP for work order {wip.work_order_number} has negative quantity completed: {wip.quantity_completed}"
            )

        if abs(wip.quantity_started - (wip.quantity_remaining + wip.quantity_completed)) > Decimal(
            "0.0001"
        ):
            result.add_error(
                f"WIP quantity mismatch: started={wip.quantity_started}, "
                f"remaining={wip.quantity_remaining}, completed={wip.quantity_completed}"
            )

        if wip.total_cost < 0:
            result.add_error(f"WIP total cost cannot be negative: {wip.total_cost}")

        calc_total = wip.material_cost + wip.labor_cost + wip.overhead_cost
        if abs(wip.total_cost - calc_total) > Decimal("0.01"):
            result.add_error(
                f"WIP total cost mismatch: {wip.total_cost} vs sum of components {calc_total}"
            )

        return result

    @staticmethod
    def validate_wip_completion(
        wip: WorkInProcessEntity, units_to_complete: Decimal
    ) -> InvariantResult:
        """
        Invariant: Cannot complete more units than remaining in WIP.

        Args:
            wip: The WIP entity.
            units_to_complete: Number of units to complete.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if units_to_complete <= 0:
            result.add_error(f"Cannot complete non-positive units: {units_to_complete}")

        if units_to_complete > wip.quantity_remaining:
            result.add_error(
                f"Cannot complete {units_to_complete} units, only {wip.quantity_remaining} remaining in WIP"
            )

        return result

    # ------------------------------------------------------------------------
    # Material Availability Invariant
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_material_availability(
        required_quantity: Decimal,
        available_quantity: Decimal,
        material_code: str,
    ) -> InvariantResult:
        """
        Invariant: Material must be available before being issued to production.

        Args:
            required_quantity: Quantity required for production.
            available_quantity: Quantity available in inventory.
            material_code: Material identifier for error message.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if required_quantity <= 0:
            result.add_error(
                f"Required quantity for material {material_code} must be positive: {required_quantity}"
            )

        if required_quantity > available_quantity:
            result.add_error(
                f"Insufficient material {material_code}: required {required_quantity}, available {available_quantity}"
            )

        return result

    # ------------------------------------------------------------------------
    # Cost Invariants
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_non_negative_cost(cost: Decimal, cost_name: str) -> InvariantResult:
        """
        Invariant: Cost values cannot be negative.

        Args:
            cost: The cost value to validate.
            cost_name: Name of the cost for error message.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)
        if cost < 0:
            result.add_error(f"{cost_name} cannot be negative: {cost}")
        return result

    @staticmethod
    def validate_standard_cost_consistency(standard_cost_entity) -> InvariantResult:
        """
        Invariant: Standard cost components must sum to total cost (within tolerance).

        Args:
            standard_cost_entity: The StandardCostEntity to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)
        calc_total = (
            standard_cost_entity.material_cost
            + standard_cost_entity.labor_cost
            + standard_cost_entity.overhead_cost
        )
        if abs(standard_cost_entity.total_cost - calc_total) > Decimal("0.01"):
            result.add_error(
                f"Standard cost total mismatch: {standard_cost_entity.total_cost} vs sum {calc_total}"
            )
        return result

    # ------------------------------------------------------------------------
    # Cross-Entity Invariants
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_work_order_bom_consistency(
        work_order: WorkOrderEntity,
        bom: BillOfMaterialsEntity,
    ) -> InvariantResult:
        """
        Invariant: Work order's BOM must exist and be compatible.

        Args:
            work_order: The work order.
            bom: The referenced BOM.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if bom is None:
            result.add_error(
                f"Work order {work_order.work_order_number} references non-existent BOM {work_order.bom_id}"
            )
        else:
            if work_order.product_id != bom.product_id:
                result.add_error(
                    f"Work order product {work_order.product_id} does not match BOM product {bom.product_id}"
                )
            if work_order.bom_version != bom.version:
                result.add_error(
                    f"Work order BOM version {work_order.bom_version} does not match BOM current version {bom.version}"
                )

        return result


# ============================================================================
# Manufacturing Invariant Enforcer
# ============================================================================


class ManufacturingInvariantEnforcer:
    """
    Enforcer for all Manufacturing invariants.

    This class coordinates invariant checks, especially those that require
    external dependencies (like material availability checking or BOM validation
    that might need database lookups). It wraps the static invariants and adds
    async capabilities where needed.

    Business context:
    Ensures that all operations on the Manufacturing aggregate maintain business
    rules and data consistency. Called before any state change.
    """

    def __init__(
        self,
        material_availability_checker: callable | None = None,
        bom_validator: callable | None = None,
    ):
        """
        Initialize the enforcer.

        Args:
            material_availability_checker: Async function that takes (material_code, required_quantity)
                                          and returns (available_quantity, InvariantResult).
            bom_validator: Async function that takes (bom_id) and returns BillOfMaterialsEntity.
        """
        self._material_checker = material_availability_checker
        self._bom_validator = bom_validator
        self._invariants = ManufacturingInvariants()
        self._violation_log: list[dict[str, Any]] = []

    def _log_violation(
        self, rule_name: str, result: InvariantResult, context: dict[str, Any]
    ) -> None:
        """Log an invariant violation for audit purposes."""
        self._violation_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "rule": rule_name,
                "errors": result.errors,
                "context": context,
            }
        )
        for error in result.errors:
            logger.error(f"Invariant violation [{rule_name}]: {error}")

    # ------------------------------------------------------------------------
    # Work Order Enforcement
    # ------------------------------------------------------------------------

    async def enforce_work_order_create(
        self,
        work_order: WorkOrderEntity,
        bom: BillOfMaterialsEntity | None = None,
    ) -> InvariantResult:
        """
        Enforce invariants when creating a work order.

        Checks:
            - Planned quantity positive
            - Dates valid
            - BOM exists and is active on planned start date

        Args:
            work_order: The work order to validate.
            bom: The BOM referenced by the work order (if available).

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        # Basic quantity and date checks
        result.merge(self._invariants.validate_work_order_quantity(work_order))
        result.merge(self._invariants.validate_work_order_dates(work_order))

        # BOM validation
        if bom:
            result.merge(self._invariants.validate_work_order_bom_consistency(work_order, bom))
            result.merge(
                self._invariants.validate_bom_effective_date(bom, work_order.planned_start_date)
            )
        elif self._bom_validator:
            try:
                bom = await self._bom_validator(work_order.bom_id)
                if bom:
                    result.merge(
                        self._invariants.validate_work_order_bom_consistency(work_order, bom)
                    )
                    result.merge(
                        self._invariants.validate_bom_effective_date(
                            bom, work_order.planned_start_date
                        )
                    )
                else:
                    result.add_error(f"BOM {work_order.bom_id} not found")
            except Exception as e:
                result.add_error(f"Failed to validate BOM: {e!s}")

        if not result.is_valid:
            self._log_violation(
                "work_order_create", result, {"work_order": work_order.work_order_number}
            )

        return result

    async def enforce_work_order_update(
        self,
        work_order: WorkOrderEntity,
    ) -> InvariantResult:
        """
        Enforce invariants when updating a work order.

        Checks:
            - Completed quantity not exceeding planned quantity

        Args:
            work_order: The work order to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = self._invariants.validate_completed_quantity(work_order)

        if not result.is_valid:
            self._log_violation(
                "work_order_update", result, {"work_order": work_order.work_order_number}
            )

        return result

    async def enforce_status_transition(
        self,
        current_status: WorkOrderStatus,
        new_status: WorkOrderStatus,
        work_order_number: str,
    ) -> InvariantResult:
        """
        Enforce valid status transition.

        Args:
            current_status: Current status.
            new_status: Desired new status.
            work_order_number: For logging.

        Returns:
            InvariantResult indicating validity.
        """
        result = self._invariants.validate_work_order_status_transition(current_status, new_status)

        if not result.is_valid:
            self._log_violation(
                "status_transition",
                result,
                {
                    "work_order": work_order_number,
                    "from": current_status.value,
                    "to": new_status.value,
                },
            )

        return result

    # ------------------------------------------------------------------------
    # Material Issue Enforcement
    # ------------------------------------------------------------------------

    async def enforce_material_issue(
        self,
        material_code: str,
        required_quantity: Decimal,
        work_order_number: str,
    ) -> InvariantResult:
        """
        Enforce material availability before issuing to production.

        Args:
            material_code: The material being issued.
            required_quantity: Quantity needed.
            work_order_number: For logging.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        if not self._material_checker:
            # If no checker provided, we cannot enforce; return warning? We'll assume valid.
            logger.warning(
                f"Material availability checker not provided; skipping check for {material_code}"
            )
            return result

        try:
            available_quantity, check_result = await self._material_checker(
                material_code, required_quantity
            )
            if check_result and not check_result.is_valid:
                result.merge(check_result)
            else:
                result.merge(
                    self._invariants.validate_material_availability(
                        required_quantity, available_quantity, material_code
                    )
                )
        except Exception as e:
            result.add_error(f"Material availability check failed for {material_code}: {e!s}")

        if not result.is_valid:
            self._log_violation(
                "material_issue",
                result,
                {
                    "work_order": work_order_number,
                    "material": material_code,
                    "required": str(required_quantity),
                },
            )

        return result

    # ------------------------------------------------------------------------
    # BOM Enforcement
    # ------------------------------------------------------------------------

    async def enforce_bom_structure(
        self,
        bom: BillOfMaterialsEntity,
    ) -> InvariantResult:
        """
        Enforce BOM structure invariants.

        Args:
            bom: The BOM to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = self._invariants.validate_bom_structure(bom)

        if not result.is_valid:
            self._log_violation("bom_structure", result, {"bom": bom.bom_code})

        return result

    async def enforce_bom_activation(
        self,
        bom: BillOfMaterialsEntity,
        activation_date: datetime,
    ) -> InvariantResult:
        """
        Enforce that a BOM can be activated.

        Checks:
            - BOM has at least one component
            - Effective date is valid

        Args:
            bom: The BOM to activate.
            activation_date: The date of activation.

        Returns:
            InvariantResult indicating validity.
        """
        result = InvariantResult(True)

        result.merge(self._invariants.validate_bom_structure(bom))

        if bom.status != BOMStatus.DRAFT:
            result.add_error(
                f"Only DRAFT BOMs can be activated, current status: {bom.status.value}"
            )

        if bom.effective_date and activation_date < bom.effective_date:
            result.add_error(
                f"Cannot activate BOM before its effective date {bom.effective_date.date()}"
            )

        if not result.is_valid:
            self._log_violation("bom_activation", result, {"bom": bom.bom_code})

        return result

    # ------------------------------------------------------------------------
    # WIP Enforcement
    # ------------------------------------------------------------------------

    async def enforce_wip_consistency(
        self,
        wip: WorkInProcessEntity,
    ) -> InvariantResult:
        """
        Enforce WIP consistency invariants.

        Args:
            wip: The WIP entity to validate.

        Returns:
            InvariantResult indicating validity.
        """
        result = self._invariants.validate_wip_consistency(wip)

        if not result.is_valid:
            self._log_violation("wip_consistency", result, {"work_order": wip.work_order_number})

        return result

    async def enforce_wip_completion(
        self,
        wip: WorkInProcessEntity,
        units_to_complete: Decimal,
    ) -> InvariantResult:
        """
        Enforce that WIP completion is possible.

        Args:
            wip: The WIP entity.
            units_to_complete: Units to complete.

        Returns:
            InvariantResult indicating validity.
        """
        result = self._invariants.validate_wip_completion(wip, units_to_complete)

        if not result.is_valid:
            self._log_violation(
                "wip_completion",
                result,
                {
                    "work_order": wip.work_order_number,
                    "units_to_complete": str(units_to_complete),
                },
            )

        return result

    # ------------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------------

    def get_violation_log(self) -> list[dict[str, Any]]:
        """Return the log of all invariant violations."""
        return self._violation_log.copy()

    def clear_violation_log(self) -> None:
        """Clear the violation log."""
        self._violation_log = []


# ============================================================================
# Alias for Backward Compatibility with service_manufacturing.py
# ============================================================================

ManufacturingInvariantsValidator = ManufacturingInvariantEnforcer


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvariantResult",
    "ManufacturingInvariantEnforcer",
    "ManufacturingInvariants",
    "ManufacturingInvariantsValidator",
]
