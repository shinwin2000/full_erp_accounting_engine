#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / Fiscal Period
Responsibility: Invariants (business rules) validation untuk Fiscal Period aggregate.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from domain.fiscal_period.aggregate_root import FiscalPeriod, PeriodStatus, PeriodType

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Result
# ============================================================================


@dataclass
class InvariantResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def __bool__(self) -> bool:
        return self.is_valid

    @classmethod
    def success(cls, warnings: list[str] | None = None) -> InvariantResult:
        return cls(is_valid=True, warnings=warnings or [])

    @classmethod
    def failure(cls, error: str, warnings: list[str] | None = None) -> InvariantResult:
        result = cls(is_valid=False, warnings=warnings or [])
        result.add_error(error)
        return result


# ============================================================================
# Common Validators
# ============================================================================


def validate_period_number(period_type: PeriodType, period_number: int) -> InvariantResult:
    if period_type == PeriodType.MONTHLY and not (1 <= period_number <= 12):
        return InvariantResult.failure(f"Monthly period number must be 1-12, got {period_number}")
    elif period_type == PeriodType.QUARTERLY and not (1 <= period_number <= 4):
        return InvariantResult.failure(f"Quarterly period number must be 1-4, got {period_number}")
    elif period_type == PeriodType.ANNUAL and period_number != 1:
        return InvariantResult.failure(f"Annual period number must be 1, got {period_number}")
    return InvariantResult.success()


def validate_date_range(start_date: datetime, end_date: datetime) -> InvariantResult:
    if start_date >= end_date:
        return InvariantResult.failure(
            f"Start date {start_date} must be before end date {end_date}"
        )
    return InvariantResult.success()


def validate_year(year: int) -> InvariantResult:
    if year < 1900 or year > 2100:
        return InvariantResult.failure(f"Year must be between 1900 and 2100, got {year}")
    return InvariantResult.success()


def validate_version(version: int, expected_version: int | None = None) -> InvariantResult:
    if version < 1:
        return InvariantResult.failure(f"Version must be >= 1, got {version}")
    if expected_version is not None and version != expected_version:
        return InvariantResult.failure(
            f"Version mismatch: expected {expected_version}, got {version}"
        )
    return InvariantResult.success()


def validate_no_overlap(
    new_start: datetime,
    new_end: datetime,
    existing_periods: list[FiscalPeriod],
    exclude_period_id: UUID | None = None,
) -> InvariantResult:
    for period in existing_periods:
        if exclude_period_id and period.period_id == exclude_period_id:
            continue
        if not (new_end <= period.start_date or new_start >= period.end_date):
            return InvariantResult.failure(
                f"Period overlaps with existing period {period.period} "
                f"({period.start_date.date()} to {period.end_date.date()})"
            )
    return InvariantResult.success()


# ============================================================================
# Period Status Transition Validators
# ============================================================================

ALLOWED_STATUS_TRANSITIONS: dict[PeriodStatus, set[PeriodStatus]] = {
    PeriodStatus.OPEN: {PeriodStatus.LOCKED, PeriodStatus.CLOSED},
    PeriodStatus.LOCKED: {PeriodStatus.OPEN, PeriodStatus.CLOSED},
    PeriodStatus.CLOSED: {PeriodStatus.OPEN},
}

TRANSITION_ROLE_REQUIREMENTS: dict[tuple[PeriodStatus, PeriodStatus], str] = {
    (PeriodStatus.OPEN, PeriodStatus.LOCKED): "accountant",
    (PeriodStatus.OPEN, PeriodStatus.CLOSED): "finance_manager",
    (PeriodStatus.LOCKED, PeriodStatus.OPEN): "finance_manager",
    (PeriodStatus.LOCKED, PeriodStatus.CLOSED): "finance_manager",
    (PeriodStatus.CLOSED, PeriodStatus.OPEN): "admin",
}


def validate_status_transition(
    current_status: PeriodStatus,
    new_status: PeriodStatus,
    user_role: str = "user",
) -> InvariantResult:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        return InvariantResult.failure(
            f"Status transition from {current_status.value} to {new_status.value} is not allowed"
        )

    required_role = TRANSITION_ROLE_REQUIREMENTS.get((current_status, new_status))
    if required_role:
        if user_role != required_role and user_role not in ("admin", "super_admin"):
            return InvariantResult.failure(
                f"Status transition requires role '{required_role}'. User has role '{user_role}'"
            )
    return InvariantResult.success()


def validate_can_close_period(
    period: FiscalPeriod,
    has_unposted_transactions: bool = False,
    has_pending_adjustments: bool = False,
) -> InvariantResult:
    result = InvariantResult()
    if period.status != PeriodStatus.LOCKED:
        result.add_error(
            f"Cannot close period that is not LOCKED (current status: {period.status.value})"
        )
    if has_unposted_transactions:
        result.add_error("Cannot close period: there are unposted transactions")
    if has_pending_adjustments:
        result.add_warning("Period has pending adjustments that should be reviewed")
    return result


def validate_can_lock_period(
    period: FiscalPeriod,
    has_open_periods_after: bool = False,
) -> InvariantResult:
    result = InvariantResult()
    if period.status != PeriodStatus.OPEN:
        result.add_error(
            f"Cannot lock period that is not OPEN (current status: {period.status.value})"
        )
    if has_open_periods_after:
        result.add_warning("There are open periods after this period")
    return result


def validate_can_reopen_period(period: FiscalPeriod, user_role: str = "user") -> InvariantResult:
    if period.status != PeriodStatus.CLOSED:
        return InvariantResult.failure(
            f"Cannot reopen period that is not CLOSED (status: {period.status.value})"
        )
    if user_role not in ("admin", "super_admin"):
        return InvariantResult.failure("Reopening a closed period requires admin role")
    return InvariantResult.success()


# ============================================================================
# Period Creation Validator
# ============================================================================


class PeriodCreationValidator:
    @staticmethod
    def validate_new_period(
        period_type: PeriodType,
        period_number: int,
        year: int,
        start_date: datetime,
        end_date: datetime,
        legal_entity_id: UUID,
        existing_periods: list[FiscalPeriod],
    ) -> InvariantResult:
        result = InvariantResult()
        result.merge(validate_period_number(period_type, period_number))
        result.merge(validate_year(year))
        result.merge(validate_date_range(start_date, end_date))
        result.merge(validate_no_overlap(start_date, end_date, existing_periods))
        return result


# ============================================================================
# Global Invariant Enforcer
# ============================================================================


class FiscalPeriodInvariantEnforcer:
    def __init__(
        self,
        get_existing_periods: Callable[[], list[FiscalPeriod]] | None = None,
    ):
        self._get_existing_periods = get_existing_periods or (lambda: [])

    async def enforce_creation(
        self,
        period_type: PeriodType,
        period_number: int,
        year: int,
        start_date: datetime,
        end_date: datetime,
        legal_entity_id: UUID,
    ) -> InvariantResult:
        existing = self._get_existing_periods()
        return PeriodCreationValidator.validate_new_period(
            period_type, period_number, year, start_date, end_date, legal_entity_id, existing
        )

    async def enforce_update(
        self,
        period_id: UUID,
        start_date: datetime,
        end_date: datetime,
        legal_entity_id: UUID,
    ) -> InvariantResult:
        existing = self._get_existing_periods()
        result = InvariantResult()
        result.merge(validate_date_range(start_date, end_date))
        result.merge(
            validate_no_overlap(start_date, end_date, existing, exclude_period_id=period_id)
        )
        return result

    async def enforce_status_transition(
        self,
        current_status: PeriodStatus,
        new_status: PeriodStatus,
        user_role: str = "user",
        has_unposted_transactions: bool = False,
        has_pending_adjustments: bool = False,
        has_open_periods_after: bool = False,
    ) -> InvariantResult:
        result = validate_status_transition(current_status, new_status, user_role)

        if result.is_valid and new_status == PeriodStatus.CLOSED:
            result.merge(
                validate_can_close_period(None, has_unposted_transactions, has_pending_adjustments)
            )
        elif result.is_valid and new_status == PeriodStatus.LOCKED:
            result.merge(validate_can_lock_period(None, has_open_periods_after))

        return result

    async def enforce_reopen(
        self,
        period: FiscalPeriod,
        user_role: str = "user",
    ) -> InvariantResult:
        # FIX: Call the correct validator that checks CLOSED status
        return validate_can_reopen_period(period, user_role)


# ============================================================================
# Standalone Validator Functions
# ============================================================================


def validate_period_before_close(
    period: FiscalPeriod,
    has_unposted_transactions: bool = False,
    has_pending_adjustments: bool = False,
) -> InvariantResult:
    result = InvariantResult()
    if not period.is_locked:
        result.add_error(
            f"Cannot close period that is not LOCKED (current status: {period.status.value})"
        )
    if has_unposted_transactions:
        result.add_error("There are unposted transactions in this period")
    if has_pending_adjustments:
        result.add_warning("Period has pending adjustments")
    return result


def validate_period_before_lock(
    period: FiscalPeriod,
    has_open_periods_after: bool = False,
) -> InvariantResult:
    result = InvariantResult()
    if not period.is_open:
        result.add_error(
            f"Cannot lock period that is not OPEN (current status: {period.status.value})"
        )
    if has_open_periods_after:
        result.add_warning("There are open periods after this period")
    return result


def can_reopen_period(period: FiscalPeriod, user_role: str = "user") -> InvariantResult:
    if not period.is_closed:
        return InvariantResult.failure(
            f"Cannot reopen period that is not CLOSED (status: {period.status.value})"
        )
    if user_role not in ("admin", "super_admin"):
        return InvariantResult.failure("Reopening a closed period requires admin role")
    return InvariantResult.success()


__all__ = [
    "FiscalPeriodInvariantEnforcer",
    "InvariantResult",
    "PeriodCreationValidator",
    "can_reopen_period",
    "validate_can_close_period",
    "validate_can_lock_period",
    "validate_can_reopen_period",
    "validate_date_range",
    "validate_no_overlap",
    "validate_period_before_close",
    "validate_period_before_lock",
    "validate_period_number",
    "validate_status_transition",
    "validate_version",
    "validate_year",
]