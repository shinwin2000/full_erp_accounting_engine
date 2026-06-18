#!/usr/bin/env python3
from __future__ import annotations

"""
Domain: Hedge
Responsibility: Hedge accounting aggregates, events, and services.
"""

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
    # Aggregate
    "EffectivenessTestResult",
    "HedgeAdjustment",
    "HedgeEffectivenessStatus",
    "HedgeError",
    "HedgeRelationship",
    "HedgeRelationshipAggregate",
    "HedgeRepository",
    "HedgeStatus",
    "HedgeType",
    "InvalidEffectivenessThresholdError",
    "InvalidHedgeTypeError",
    # Domain Events
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "HedgeAmountReclassified",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelled",
    "HedgeCancelledEvent",
    "HedgeDesignated",
    "HedgeDesignatedEvent",
    "HedgeDiscontinued",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessTested",
    "HedgeEffectivenessTestedEvent",
    "HedgeFairValueAdjusted",
    "HedgeFairValueAdjustedEvent",
    # Effectiveness Tester
    "EffectivenessTestDataPoint",
    "EffectivenessTestError",
    "HedgeEffectivenessTester",
    "TesterEffectivenessTestResult",
    # Hedge Instrument
    "HedgeInstrument",
    "HedgeInstrumentError",
    "HedgeInstrumentRepository",
    "InstrumentFairValueHistory",
    "InstrumentStatus",
    "InstrumentType",
    # Hedged Item
    "HedgedItem",
    "HedgedItemAdjustment",
    "HedgedItemError",
    "HedgedItemRepository",
    "HedgedItemStatus",
    "HedgedItemType",
]
