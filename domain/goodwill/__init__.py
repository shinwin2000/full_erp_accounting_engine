#!/usr/bin/env python3
from __future__ import annotations

"""
Domain: Goodwill
Responsibility: Goodwill accounting and impairment testing (PSAK 48 / IFRS 3, IAS 36).
"""

from .aggregate_root import (
    Goodwill,
    GoodwillAggregate,
    GoodwillAllocation,
    GoodwillError,
    GoodwillImpairmentHistory,
    GoodwillRepository,
    GoodwillStatus,
    InvalidGoodwillAmountError,
    InvalidImpairmentAmountError,
    InvalidReversalAmountError,
)
from .domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    GoodwillAmortized,
    GoodwillAmortizedEvent,
    GoodwillDisposedEvent,
    GoodwillImpaired,
    GoodwillImpairedEvent,
    GoodwillImpairmentReversedEvent,
    GoodwillRecognized,
    GoodwillRecognizedEvent,
)
from .impairment_tester import (
    CGUAllocation,
    GoodwillImpairmentTester,
    ImpairmentTestError,
    ImpairmentTestResult,
)

__all__ = [
    # Aggregate
    "Goodwill",
    "GoodwillAggregate",
    "GoodwillAllocation",
    "GoodwillError",
    "GoodwillImpairmentHistory",
    "GoodwillRepository",
    "GoodwillStatus",
    "InvalidGoodwillAmountError",
    "InvalidImpairmentAmountError",
    "InvalidReversalAmountError",
    # Domain Events
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "GoodwillAmortized",
    "GoodwillAmortizedEvent",
    "GoodwillDisposedEvent",
    "GoodwillImpaired",
    "GoodwillImpairedEvent",
    "GoodwillImpairmentReversedEvent",
    "GoodwillRecognized",
    "GoodwillRecognizedEvent",
    # Impairment Tester
    "CGUAllocation",
    "GoodwillImpairmentTester",
    "ImpairmentTestError",
    "ImpairmentTestResult",
]
