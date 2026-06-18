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
)
from .domain_events import (
    BudgetApproved,
    BudgetArchived,
    BudgetCancelled,
    BudgetClosed,
    BudgetCreated,
    BudgetEventPublisher,
    BudgetEventType,
    BudgetLineAdded,
    BudgetLineAdjusted,
    BudgetLineRemoved,
    BudgetRejected,
    BudgetRevised,
    BudgetStatusChanged,
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
    # Events
    "BudgetApproved",
    "BudgetArchived",
    "BudgetCancelled",
    "BudgetClosed",
    "BudgetCreated",
    "BudgetEventPublisher",
    "BudgetEventType",
    "BudgetLineAdded",
    "BudgetLineAdjusted",
    "BudgetLineRemoved",
    "BudgetRejected",
    "BudgetRevised",
    "BudgetStatusChanged",
    "DomainEvent",
    # Variance
    "VarianceCalculator",
    "VarianceResult",
    "VarianceType",
]
