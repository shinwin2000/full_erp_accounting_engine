#!/usr/bin/env python3
"""
Domain: Budget
Responsibility: Budget management and variance analysis.
"""

from __future__ import annotations

from .aggregate_root import (
    Budget,
    BudgetAggregate,
    BudgetLine,
    BudgetLineItem,
    BudgetPeriod,
    BudgetRepository,
    BudgetStatus,
    BudgetType,
)
from .domain_events import (
    # Tanpa suffix (untuk kompatibilitas)
    BudgetActivated,
    # Dengan suffix "Event"
    BudgetActivatedEvent,
    BudgetApproved,
    BudgetApprovedEvent,
    BudgetArchived,
    BudgetArchivedEvent,
    BudgetCancelled,
    BudgetCancelledEvent,
    BudgetClosed,
    BudgetClosedEvent,
    BudgetCreated,
    BudgetCreatedEvent,
    BudgetEventPublisher,
    BudgetEventType,
    BudgetLineAdded,
    BudgetLineAddedEvent,
    BudgetLineAdjusted,
    BudgetLineAdjustedEvent,
    BudgetLineRemoved,
    BudgetLineRemovedEvent,
    BudgetLocked,
    BudgetLockedEvent,
    BudgetRejected,
    BudgetRejectedEvent,
    BudgetRevised,
    BudgetRevisedEvent,
    BudgetStatusChanged,
    BudgetStatusChangedEvent,
    BudgetSubmitted,
    BudgetSubmittedEvent,
    BudgetUnlocked,
    BudgetUnlockedEvent,
    DomainEvent,
)
from .variance_calculator import VarianceCalculator, VarianceResult, VarianceType

__all__ = [
    # Aggregates
    "Budget",
    # Events (tanpa suffix)
    "BudgetActivated",
    # Events (dengan suffix)
    "BudgetActivatedEvent",
    "BudgetAggregate",
    "BudgetApproved",
    "BudgetApprovedEvent",
    "BudgetArchived",
    "BudgetArchivedEvent",
    "BudgetCancelled",
    "BudgetCancelledEvent",
    "BudgetClosed",
    "BudgetClosedEvent",
    "BudgetCreated",
    "BudgetCreatedEvent",
    "BudgetEventPublisher",
    "BudgetEventType",
    "BudgetLine",
    "BudgetLineAdded",
    "BudgetLineAddedEvent",
    "BudgetLineAdjusted",
    "BudgetLineAdjustedEvent",
    "BudgetLineItem",
    "BudgetLineRemoved",
    "BudgetLineRemovedEvent",
    "BudgetLocked",
    "BudgetLockedEvent",
    "BudgetPeriod",
    "BudgetRejected",
    "BudgetRejectedEvent",
    "BudgetRepository",
    "BudgetRevised",
    "BudgetRevisedEvent",
    "BudgetStatus",
    "BudgetStatusChanged",
    "BudgetStatusChangedEvent",
    "BudgetSubmitted",
    "BudgetSubmittedEvent",
    "BudgetType",
    "BudgetUnlocked",
    "BudgetUnlockedEvent",
    "DomainEvent",
    # Variance
    "VarianceCalculator",
    "VarianceResult",
    "VarianceType",
]
