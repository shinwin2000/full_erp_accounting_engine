#!/usr/bin/env python3
"""
Domain: Hedge
Responsibility: Hedge accounting aggregates, events, and services.
"""

from __future__ import annotations

from .aggregate_root import (
    EffectivenessTestResult,
    HedgeAdjustment,
    HedgeEffectivenessStatus,
    HedgeError,
    HedgeRelationship,
    HedgeRelationshipAggregate,
    HedgeRepository,
    HedgeStatus,
    HedgeType,
    InvalidEffectivenessThresholdError,
    InvalidHedgeTypeError,
)
from .domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    HedgeAmountReclassified,
    HedgeAmountReclassifiedEvent,
    HedgeCancelled,
    HedgeCancelledEvent,
    HedgeDesignated,
    HedgeDesignatedEvent,
    HedgeDiscontinued,
    HedgeDiscontinuedEvent,
    HedgeEffectivenessTested,
    HedgeEffectivenessTestedEvent,
    HedgeFairValueAdjusted,
    HedgeFairValueAdjustedEvent,
)
from .hedge_effectiveness_tester import (
    EffectivenessTestDataPoint,
    EffectivenessTestError,
    HedgeEffectivenessTester,
)
from .hedge_effectiveness_tester import (
    EffectivenessTestResult as TesterEffectivenessTestResult,
)
from .hedge_instrument import (
    HedgeInstrument,
    HedgeInstrumentError,
    HedgeInstrumentRepository,
    InstrumentFairValueHistory,
    InstrumentStatus,
    InstrumentType,
)
from .hedged_item import (
    HedgedItem,
    HedgedItemAdjustment,
    HedgedItemError,
    HedgedItemRepository,
    HedgedItemStatus,
    HedgedItemType,
)

__all__ = [
    # Domain Events
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    # Effectiveness Tester
    "EffectivenessTestDataPoint",
    "EffectivenessTestError",
    "EffectivenessTestResult",
    # Aggregate
    "HedgeAdjustment",
    "HedgeAmountReclassified",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelled",
    "HedgeCancelledEvent",
    "HedgeDesignated",
    "HedgeDesignatedEvent",
    "HedgeDiscontinued",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessStatus",
    "HedgeEffectivenessTested",
    "HedgeEffectivenessTestedEvent",
    "HedgeEffectivenessTester",
    "HedgeError",
    "HedgeFairValueAdjusted",
    "HedgeFairValueAdjustedEvent",
    "HedgeInstrument",
    "HedgeInstrumentError",
    "HedgeInstrumentRepository",
    "HedgeRelationship",
    "HedgeRelationshipAggregate",
    "HedgeRepository",
    "HedgeStatus",
    "HedgeType",
    "HedgedItem",
    "HedgedItemAdjustment",
    "HedgedItemError",
    "HedgedItemRepository",
    "HedgedItemStatus",
    "HedgedItemType",
    "InstrumentFairValueHistory",
    "InstrumentStatus",
    "InstrumentType",
    "InvalidEffectivenessThresholdError",
    "InvalidHedgeTypeError",
    "TesterEffectivenessTestResult",
]
