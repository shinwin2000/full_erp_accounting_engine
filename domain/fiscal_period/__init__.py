#!/usr/bin/env python3
"""
Package: domain.fiscal_period

Fiscal Period domain module.

Exports all public classes, enums, value objects, aggregates,
events, validators, and repository protocols.
"""

from domain.fiscal_period.aggregate_root import (
    AccountingPeriod,
    FiscalPeriod,
    FiscalPeriodError,
    FiscalPeriodRepository,
    InvalidDateRangeError,
    InvalidPeriodNumberError,
    InvalidStatusTransitionError,
    PeriodNotFoundError,
    PeriodStatus,
    PeriodType,
)
from domain.fiscal_period.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    PeriodClosedEvent,
    PeriodCreatedEvent,
    PeriodLockedEvent,
    PeriodOpenedEvent,
    PeriodReopenedEvent,
    PeriodUpdatedEvent,
    deserialize_domain_event,
    serialize_domain_event,
)
from domain.fiscal_period.invariants import (
    FiscalPeriodInvariantEnforcer,
    InvariantResult,
    PeriodCreationValidator,
    can_reopen_period,
    validate_can_close_period,
    validate_can_lock_period,
    validate_date_range,
    validate_no_overlap,
    validate_period_before_close,
    validate_period_before_lock,
    validate_period_number,
    validate_status_transition,
    validate_version,
    validate_year,
)

__all__ = [
    "AccountingPeriod",
    "DomainEvent",
    "DomainEventPublisher",
    # Domain Events
    "DomainEventType",
    "FiscalPeriod",
    # Exceptions
    "FiscalPeriodError",
    "FiscalPeriodInvariantEnforcer",
    "FiscalPeriodRepository",
    "InvalidDateRangeError",
    "InvalidPeriodNumberError",
    "InvalidStatusTransitionError",
    # Invariants & Validators
    "InvariantResult",
    "PeriodClosedEvent",
    "PeriodCreatedEvent",
    "PeriodCreationValidator",
    "PeriodLockedEvent",
    "PeriodNotFoundError",
    "PeriodOpenedEvent",
    "PeriodReopenedEvent",
    # Aggregate and Value Objects
    "PeriodStatus",
    "PeriodType",
    "PeriodUpdatedEvent",
    "can_reopen_period",
    "deserialize_domain_event",
    "serialize_domain_event",
    "validate_can_close_period",
    "validate_can_lock_period",
    "validate_date_range",
    "validate_no_overlap",
    "validate_period_before_close",
    "validate_period_before_lock",
    "validate_period_number",
    "validate_status_transition",
    "validate_version",
    "validate_year",
]
