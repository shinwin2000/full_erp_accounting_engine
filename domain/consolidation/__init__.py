#!/usr/bin/env python3
from __future__ import annotations

"""
Module: domain/consolidation/__init__.py
Layer: Domain / Consolidation
Responsibility: Package untuk konsolidasi laporan keuangan grup perusahaan.
"""

from .aggregate_root import (
    ConsolidationAggregate,
    ConsolidationGroup,
    ConsolidationGroupRepository,
    ConsolidationStatus,
)
from .domain_events import (
    ConsolidationCancelled,
    ConsolidationCompleted,
    ConsolidationCreated,
    ConsolidationEventPublisher,
    ConsolidationEventType,
    ConsolidationStarted,
    DomainEvent,
    EliminationEntryCreated,
    IntercompanyTransactionDetected,
    NCICalculated,
)
from .elimination_entry import EliminationEntry
from .foreign_currency_translator import (
    ExchangeRateNotFoundError,
    ExchangeRateProvider,
    ForeignCurrencyTranslator,
    InMemoryExchangeRateProvider,
)
from .intercompany_transaction import (
    IntercompanyTransaction,
    IntercompanyTransactionRepository,
    IntercompanyTransactionStatus,
    TransactionType,
)
from .non_controlling_interest import (
    NCICalculationResult,
    NonControllingInterestCalculator,
)

__all__ = [
    # Aggregate
    "ConsolidationAggregate",
    "ConsolidationGroup",
    "ConsolidationGroupRepository",
    "ConsolidationStatus",
    # Events
    "ConsolidationCancelled",
    "ConsolidationCompleted",
    "ConsolidationCreated",
    "ConsolidationEventPublisher",
    "ConsolidationEventType",
    "ConsolidationStarted",
    "DomainEvent",
    "EliminationEntryCreated",
    "IntercompanyTransactionDetected",
    "NCICalculated",
    # Entities
    "EliminationEntry",
    "IntercompanyTransaction",
    "IntercompanyTransactionRepository",
    "IntercompanyTransactionStatus",
    "TransactionType",
    # Value Objects / Services
    "ExchangeRateNotFoundError",
    "ExchangeRateProvider",
    "ForeignCurrencyTranslator",
    "InMemoryExchangeRateProvider",
    "NCICalculationResult",
    "NonControllingInterestCalculator",
]
