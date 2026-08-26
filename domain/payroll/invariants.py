#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Payroll
Responsibility: Business invariants for payroll.

Defines all invariants that must be satisfied by the Payroll aggregate.
Ensures payroll data is always in a valid business and regulatory state.

Dependencies:
- Python standard library (logging, decimal, datetime)
- domain.payroll.payroll_run_entity (PayrollRunEntity, PayrollRunStatus)
- domain.payroll.employee_salary_structure_vo (EmployeeSalaryStructureVO)

Audit: Every invariant violation is logged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from domain.payroll.employee_salary_structure_vo import EmployeeSalaryStructureVO
from domain.payroll.payroll_run_entity import PayrollRunEntity, PayrollRunStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Validation Result
# ============================================================================


class InvariantResult:
    """Result of invariant validation."""

    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False
        logger.warning(f"Invariant violation: {error}")

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"is_valid": self.is_valid, "errors": self.errors, "error_count": len(self.errors)}

    def __bool__(self) -> bool:
        return self.is_valid


# ============================================================================
# Payroll Invariants (Static Methods)
# ============================================================================


class PayrollInvariants:
    """Collection of static invariant validation methods."""

    # ------------------------------------------------------------------------
    # Salary structure invariants
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_basic_salary(
        salary: Decimal, regional_minimum_wage: Decimal | None = None
    ) -> InvariantResult:
        """Invariant: Basic salary must be above regional minimum wage (UMR)."""
        result = InvariantResult(True)
        if salary <= 0:
            result.add_error(f"Basic salary must be positive: {salary}")
        if regional_minimum_wage and salary < regional_minimum_wage:
            result.add_error(
                f"Basic salary {salary} is below regional minimum wage {regional_minimum_wage}"
            )
        return result

    @staticmethod
    def validate_net_salary(net_salary: Decimal) -> InvariantResult:
        """Invariant: Net salary cannot be negative."""
        result = InvariantResult(True)
        if net_salary < 0:
            result.add_error(f"Net salary cannot be negative: {net_salary}")
        return result

    @staticmethod
    def validate_tax_calculation(
        gross_salary: Decimal, tax: Decimal, net_salary: Decimal
    ) -> InvariantResult:
        """Invariant: Tax must not exceed gross salary and net must be consistent."""
        result = InvariantResult(True)
        if tax < 0:
            result.add_error(f"Tax cannot be negative: {tax}")
        if tax > gross_salary:
            result.add_error(f"Tax {tax} exceeds gross salary {gross_salary}")
        # Allow small rounding difference
        expected_net = gross_salary - tax
        if abs(net_salary - expected_net) > Decimal("0.01"):
            result.add_error(
                f"Net salary mismatch: gross={gross_salary}, tax={tax}, net={net_salary}"
            )
        return result

    @staticmethod
    def validate_employee_structure(structure: EmployeeSalaryStructureVO) -> InvariantResult:
        """Invariant: Employee structure must have valid components."""
        result = InvariantResult(True)
        # Check for duplicate component names
        component_names = set()
        for comp in structure.salary_components:
            if comp.component_name in component_names:
                result.add_error(f"Duplicate component name: {comp.component_name}")
            component_names.add(comp.component_name)
        # Check total salary not negative
        if structure.total_salary < 0:
            result.add_error(f"Total salary cannot be negative: {structure.total_salary}")
        return result

    # ------------------------------------------------------------------------
    # Payroll run status transitions
    # ------------------------------------------------------------------------

    @staticmethod
    def validate_payroll_run_status_transition(
        current_status: PayrollRunStatus,
        new_status: PayrollRunStatus,
    ) -> InvariantResult:
        """Invariant: Status transitions must follow allowed paths."""
        result = InvariantResult(True)

        valid_transitions = {
            PayrollRunStatus.DRAFT: [PayrollRunStatus.CALCULATED, PayrollRunStatus.CANCELLED],
            PayrollRunStatus.CALCULATED: [PayrollRunStatus.APPROVED, PayrollRunStatus.CANCELLED],
            PayrollRunStatus.APPROVED: [PayrollRunStatus.PAID, PayrollRunStatus.CANCELLED],
            PayrollRunStatus.PAID: [],
            PayrollRunStatus.CANCELLED: [],
        }

        allowed = valid_transitions.get(current_status, [])
        if new_status not in allowed:
            result.add_error(
                f"Invalid status transition from {current_status.value} to {new_status.value}"
            )
        return result

    @staticmethod
    def validate_payment_amount(total_net: Decimal, payment_amount: Decimal) -> InvariantResult:
        """Invariant: Payment amount must equal total net pay."""
        result = InvariantResult(True)
        if payment_amount != total_net:
            result.add_error(
                f"Payment amount {payment_amount} does not match total net pay {total_net}"
            )
        return result

    @staticmethod
    def validate_period_uniqueness(
        year: int,
        month: int,
        existing_runs: list[PayrollRunEntity],
    ) -> InvariantResult:
        """Invariant: No two non-cancelled payroll runs for same period."""
        result = InvariantResult(True)
        for run in existing_runs:
            if (
                run.period_year == year
                and run.period_month == month
                and run.status != PayrollRunStatus.CANCELLED
            ):
                result.add_error(f"Payroll run already exists for {month}/{year}")
                break
        return result


# ============================================================================
# Payroll Invariant Enforcer
# ============================================================================


class PayrollInvariantEnforcer:
    """Enforcer for all Payroll invariants with async dependencies."""

    def __init__(
        self,
        period_checker: Callable | None = None,
        umr_checker: Callable | None = None,
    ):
        self._period_checker = period_checker
        self._umr_checker = umr_checker
        self._invariants = PayrollInvariants()

    async def enforce_salary_structure(
        self, structure: EmployeeSalaryStructureVO
    ) -> InvariantResult:
        """Enforce all invariants for salary structure."""
        result = InvariantResult(True)

        # Get UMR for this legal entity and effective date
        umr = None
        if self._umr_checker:
            try:
                umr = await self._umr_checker(
                    structure.legal_entity_id,
                    structure.effective_date or datetime.now(UTC),
                )
            except Exception as e:
                logger.warning(f"Failed to get UMR: {e}")

        result.merge(self._invariants.validate_basic_salary(structure.basic_salary, umr))
        result.merge(self._invariants.validate_employee_structure(structure))
        return result

    async def enforce_payroll_calculation(
        self,
        gross_salary: Decimal,
        tax: Decimal,
        net_salary: Decimal,
    ) -> InvariantResult:
        """Enforce invariants for payroll calculation."""
        result = InvariantResult(True)
        result.merge(self._invariants.validate_net_salary(net_salary))
        result.merge(self._invariants.validate_tax_calculation(gross_salary, tax, net_salary))
        return result

    async def enforce_status_transition(
        self,
        current_status: PayrollRunStatus,
        new_status: PayrollRunStatus,
    ) -> InvariantResult:
        """Enforce valid status transition."""
        return self._invariants.validate_payroll_run_status_transition(current_status, new_status)

    async def enforce_payment(self, total_net: Decimal, payment_amount: Decimal) -> InvariantResult:
        """Enforce payment amount matches total net."""
        return self._invariants.validate_payment_amount(total_net, payment_amount)

    async def enforce_period_uniqueness(
        self,
        year: int,
        month: int,
        existing_runs: list[PayrollRunEntity],
    ) -> InvariantResult:
        """Enforce no duplicate period."""
        return self._invariants.validate_period_uniqueness(year, month, existing_runs)


# ============================================================================
# Compatibility Class for Service Layer
# ============================================================================


class PayrollInvariantsValidator:
    """Simple validator for compatibility with service layer."""

    def __init__(self):
        self._invariants = PayrollInvariants()

    def validate_basic_salary(self, salary: Decimal) -> InvariantResult:
        return self._invariants.validate_basic_salary(salary)

    def validate_net_salary(self, net_salary: Decimal) -> InvariantResult:
        return self._invariants.validate_net_salary(net_salary)

    def validate_tax_calculation(
        self, gross_salary: Decimal, tax: Decimal, net_salary: Decimal
    ) -> InvariantResult:
        return self._invariants.validate_tax_calculation(gross_salary, tax, net_salary)

    def validate_employee_structure(self, structure: EmployeeSalaryStructureVO) -> InvariantResult:
        return self._invariants.validate_employee_structure(structure)

    def validate_status_transition(
        self, current_status: PayrollRunStatus, new_status: PayrollRunStatus
    ) -> InvariantResult:
        return self._invariants.validate_payroll_run_status_transition(current_status, new_status)

    def validate_payment_amount(
        self, total_net: Decimal, payment_amount: Decimal
    ) -> InvariantResult:
        return self._invariants.validate_payment_amount(total_net, payment_amount)

    def validate_period_uniqueness(
        self, year: int, month: int, existing_runs: list[PayrollRunEntity]
    ) -> InvariantResult:
        return self._invariants.validate_period_uniqueness(year, month, existing_runs)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvariantResult",
    "PayrollInvariantEnforcer",
    "PayrollInvariants",
    "PayrollInvariantsValidator",
]
