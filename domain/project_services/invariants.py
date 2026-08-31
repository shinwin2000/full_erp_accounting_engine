#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Project & Services
Responsibility: Aturan: Progres tidak boleh > 100%, biaya tidak negatif, dll.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.project_services.project_entity import ProjectStatus
from domain.project_services.time_entry_entity import TimeEntryEntity

logger = logging.getLogger(__name__)


class InvariantResult:
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


class ProjectInvariants:
    @staticmethod
    def validate_project_code_unique(
        project_code: str, existing_codes: set[str]
    ) -> InvariantResult:
        result = InvariantResult(True)
        if project_code in existing_codes:
            result.add_error(f"Project code '{project_code}' already exists")
        return result

    @staticmethod
    def validate_contract_value(contract_value: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if contract_value < 0:
            result.add_error(f"Contract value cannot be negative: {contract_value}")
        return result

    @staticmethod
    def validate_project_dates(start_date: datetime, end_date: datetime) -> InvariantResult:
        result = InvariantResult(True)
        if end_date <= start_date:
            result.add_error(f"End date {end_date} must be after start date {start_date}")
        return result

    @staticmethod
    def validate_project_status_transition(
        current_status: ProjectStatus, new_status: ProjectStatus
    ) -> InvariantResult:
        result = InvariantResult(True)
        valid_transitions = {
            ProjectStatus.DRAFT: [ProjectStatus.ACTIVE, ProjectStatus.CANCELLED],
            ProjectStatus.ACTIVE: [
                ProjectStatus.ON_HOLD,
                ProjectStatus.COMPLETED,
                ProjectStatus.CANCELLED,
            ],
            ProjectStatus.ON_HOLD: [ProjectStatus.ACTIVE, ProjectStatus.CANCELLED],
            ProjectStatus.COMPLETED: [],
            ProjectStatus.CANCELLED: [],
        }
        allowed = valid_transitions.get(current_status, [])
        if new_status not in allowed:
            result.add_error(
                f"Invalid status transition from {current_status.value} to {new_status.value}"
            )
        return result


class CostTrackerInvariants:
    @staticmethod
    def validate_cost_amount(amount: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if amount < 0:
            result.add_error(f"Cost amount cannot be negative: {amount}")
        return result


class TimeEntryInvariants:
    @staticmethod
    def validate_hours(hours: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if hours <= 0:
            result.add_error(f"Hours must be positive: {hours}")
        if hours > 24:
            result.add_error(f"Hours cannot exceed 24 per day: {hours}")
        return result

    @staticmethod
    def validate_entry_date(entry_date: datetime) -> InvariantResult:
        result = InvariantResult(True)
        today = datetime.now(UTC)
        if entry_date > today:
            result.add_error(f"Entry date cannot be in the future: {entry_date}")
        return result

    @staticmethod
    def validate_duplicate_entry(
        employee_id: UUID, entry_date: datetime, existing_entries: list[TimeEntryEntity]
    ) -> InvariantResult:
        result = InvariantResult(True)
        for existing in existing_entries:
            if (
                existing.employee_id == employee_id
                and existing.entry_date.date() == entry_date.date()
            ):
                result.add_error(f"Time entry already exists for employee on {entry_date.date()}")
                break
        return result


class RevenueRecognitionInvariants:
    @staticmethod
    def validate_recognized_revenue(
        recognized_revenue: Decimal, contract_value: Decimal
    ) -> InvariantResult:
        result = InvariantResult(True)
        if recognized_revenue > contract_value:
            result.add_error(
                f"Recognized revenue {recognized_revenue} exceeds contract value {contract_value}"
            )
        return result

    @staticmethod
    def validate_cumulative_percentage(percentage: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if percentage < 0 or percentage > 100:
            result.add_error(f"Completion percentage must be between 0 and 100: {percentage}")
        return result


class RetainerContractInvariants:
    @staticmethod
    def validate_monthly_fee(fee: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if fee <= 0:
            result.add_error(f"Monthly fee must be positive: {fee}")
        return result

    @staticmethod
    def validate_allocated_hours(hours: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if hours <= 0:
            result.add_error(f"Allocated hours must be positive: {hours}")
        return result


class ProjectServicesInvariantEnforcer:
    def __init__(self, project_code_checker: Callable[[], set[str]] | None = None):
        self._project_code_checker: Callable[[], set[str]] = project_code_checker or (lambda: set())
        self._project_invariants = ProjectInvariants()
        self._cost_tracker_invariants = CostTrackerInvariants()
        self._time_entry_invariants = TimeEntryInvariants()
        self._revenue_invariants = RevenueRecognitionInvariants()
        self._retainer_invariants = RetainerContractInvariants()
        self._violation_log: list[dict[str, Any]] = []

    def _log_violation(
        self, rule_name: str, result: InvariantResult, context: dict[str, Any]
    ) -> None:
        self._violation_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "rule": rule_name,
                "errors": result.errors,
                "context": context,
            }
        )

    async def enforce_project_create(
        self,
        project_code: str,
        contract_value: Decimal,
        start_date: datetime,
        expected_end_date: datetime,
    ) -> InvariantResult:
        result = InvariantResult(True)
        existing_codes = self._project_code_checker()  # no await, it's synchronous
        result.merge(
            self._project_invariants.validate_project_code_unique(project_code, existing_codes)
        )
        result.merge(self._project_invariants.validate_contract_value(contract_value))
        result.merge(self._project_invariants.validate_project_dates(start_date, expected_end_date))
        return result

    async def enforce_project_status_transition(
        self, current_status: ProjectStatus, new_status: ProjectStatus
    ) -> InvariantResult:
        return self._project_invariants.validate_project_status_transition(
            current_status, new_status
        )

    async def enforce_cost_entry(self, amount: Decimal) -> InvariantResult:
        return self._cost_tracker_invariants.validate_cost_amount(amount)

    async def enforce_time_entry(
        self,
        employee_id: UUID,
        hours: Decimal,
        entry_date: datetime,
        existing_entries: list[TimeEntryEntity],
    ) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self._time_entry_invariants.validate_hours(hours))
        result.merge(self._time_entry_invariants.validate_entry_date(entry_date))
        result.merge(
            self._time_entry_invariants.validate_duplicate_entry(
                employee_id, entry_date, existing_entries
            )
        )
        return result

    async def enforce_revenue_recognition(
        self, recognized_revenue: Decimal, contract_value: Decimal, cumulative_percentage: Decimal
    ) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(
            self._revenue_invariants.validate_recognized_revenue(recognized_revenue, contract_value)
        )
        result.merge(self._revenue_invariants.validate_cumulative_percentage(cumulative_percentage))
        return result

    async def enforce_retainer_contract(
        self, monthly_fee: Decimal, allocated_hours: Decimal
    ) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self._retainer_invariants.validate_monthly_fee(monthly_fee))
        result.merge(self._retainer_invariants.validate_allocated_hours(allocated_hours))
        return result

    def get_violation_log(self) -> list[dict[str, Any]]:
        return self._violation_log.copy()

    def clear_violation_log(self) -> None:
        self._violation_log = []


ProjectInvariantsValidator = ProjectServicesInvariantEnforcer

__all__ = [
    "CostTrackerInvariants",
    "InvariantResult",
    "ProjectInvariants",
    "ProjectInvariantsValidator",
    "ProjectServicesInvariantEnforcer",
    "RetainerContractInvariants",
    "RevenueRecognitionInvariants",
    "TimeEntryInvariants",
]
