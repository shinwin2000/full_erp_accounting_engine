#!/usr/bin/env python3
from __future__ import annotations

"""
Domain: Budget
Responsibility: Budget management and variance analysis.
"""

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
    "BudgetAggregate",
    "BudgetLine",
    "BudgetLineItem",
    "BudgetPeriod",
    "BudgetRepository",
    "BudgetStatus",
    "BudgetType",
    # Events (tanpa suffix)
    "BudgetActivated",
    "BudgetApproved",
    "BudgetArchived",
    "BudgetCancelled",
    "BudgetClosed",
    "BudgetCreated",
    "BudgetLineAdded",
    "BudgetLineAdjusted",
    "BudgetLineRemoved",
    "BudgetLocked",
    "BudgetRejected",
    "BudgetRevised",
    "BudgetStatusChanged",
    "BudgetSubmitted",
    "BudgetUnlocked",
    # Events (dengan suffix)
    "BudgetActivatedEvent",
    "BudgetApprovedEvent",
    "BudgetArchivedEvent",
    "BudgetCancelledEvent",
    "BudgetClosedEvent",
    "BudgetCreatedEvent",
    "BudgetEventPublisher",
    "BudgetEventType",
    "BudgetLineAddedEvent",
    "BudgetLineAdjustedEvent",
    "BudgetLineRemovedEvent",
    "BudgetLockedEvent",
    "BudgetRejectedEvent",
    "BudgetRevisedEvent",
    "BudgetStatusChangedEvent",
    "BudgetSubmittedEvent",
    "BudgetUnlockedEvent",
    "DomainEvent",
    # Variance
    "VarianceCalculator",
    "VarianceResult",
    "VarianceType",
]
