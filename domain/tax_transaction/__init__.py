#!/usr/bin/env python3
"""
Domain module for tax transactions.

Exports all aggregates, value objects, invariants, repositories, and domain events.
"""

from .aggregate_root import (
    Bupot,
    EMeterai,
    FakturPajak,
    FakturStatus,
    SPTStatus,
    SPTSubmission,
)
from .domain_events import (
    BupotApprovedEvent,
    BupotSubmittedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    FakturApprovedEvent,
    FakturRejectedEvent,
    FakturSubmittedEvent,
    MeteraiUsedEvent,
    SPTApprovedEvent,
    SPTSubmittedEvent,
)
from .invariants import InvariantResult, TaxInvariantEnforcer, TaxInvariants
from .repositories import (
    BupotRepository,
    EMeteraiRepository,
    FakturPajakRepository,
    SPTRepository,
)
from .value_objects import (
    NPWP,
    NPWPVO,
    NSFP,
    NSFPVO,
    FakturNumberVO,
    KodeBilling,
    KodeFaktur,
    MasaPajak,
    TarifPajak,
    TaxPeriodVO,
)

__all__ = [
    # Aggregates
    "Bupot",
    "EMeterai",
    "FakturPajak",
    "FakturStatus",
    "SPTStatus",
    "SPTSubmission",
    # Domain Events
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "FakturSubmittedEvent",
    "FakturApprovedEvent",
    "FakturRejectedEvent",
    "SPTSubmittedEvent",
    "SPTApprovedEvent",
    "BupotSubmittedEvent",
    "BupotApprovedEvent",
    "MeteraiUsedEvent",
    # Value Objects
    "NPWPVO",
    "NSFPVO",
    "TaxPeriodVO",
    "FakturNumberVO",
    "NPWP",
    "NSFP",
    "MasaPajak",
    "KodeFaktur",
    "TarifPajak",
    "KodeBilling",
    # Invariants
    "InvariantResult",
    "TaxInvariants",
    "TaxInvariantEnforcer",
    # Repositories
    "FakturPajakRepository",
    "SPTRepository",
    "BupotRepository",
    "EMeteraiRepository",
]
