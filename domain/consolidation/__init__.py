#!/usr/bin/env python3
from __future__ import annotations

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

"""
Module: domain/consolidation/__init__.py
Layer: Domain / Consolidation
Responsibility: Package untuk konsolidasi laporan keuangan grup perusahaan.
"""

__all__ = [
    "ConsolidationAggregate",
    "ConsolidationCancelled",
    "ConsolidationCompleted",
    "ConsolidationCreated",
    "ConsolidationEventPublisher",
    "ConsolidationEventType",
    "ConsolidationGroup",
    "ConsolidationGroupRepository",
    "ConsolidationStarted",
    "ConsolidationStatus",
    "DomainEvent",
    "EliminationEntry",
    "EliminationEntryCreated",
    "ExchangeRateNotFoundError",
    "ExchangeRateProvider",
    "ForeignCurrencyTranslator",
    "InMemoryExchangeRateProvider",
    "IntercompanyTransaction",
    "IntercompanyTransactionDetected",
    "IntercompanyTransactionRepository",
    "IntercompanyTransactionStatus",
    "NCICalculated",
    "NCICalculationResult",
    "NonControllingInterestCalculator",
    "TransactionType",
]
