#!/usr/bin/env python3
from __future__ import annotations

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

"""
Domain: Goodwill
Responsibility: Goodwill accounting and impairment testing (PSAK 48 / IFRS 3, IAS 36).
"""

__all__ = [
    "CGUAllocation",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "Goodwill",
    "GoodwillAggregate",
    "GoodwillAllocation",
    "GoodwillAmortized",
    "GoodwillAmortizedEvent",
    "GoodwillDisposedEvent",
    "GoodwillError",
    "GoodwillImpaired",
    "GoodwillImpairedEvent",
    "GoodwillImpairmentHistory",
    "GoodwillImpairmentReversedEvent",
    "GoodwillImpairmentTester",
    "GoodwillRecognized",
    "GoodwillRecognizedEvent",
    "GoodwillRepository",
    "GoodwillStatus",
    "ImpairmentTestError",
    "ImpairmentTestResult",
    "InvalidGoodwillAmountError",
    "InvalidImpairmentAmountError",
    "InvalidReversalAmountError",
]
