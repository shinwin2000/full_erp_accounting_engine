from __future__ import annotations

"""
Package: domain.forex
Foreign exchange revaluation domain.
"""

from domain.forex.aggregate_root import (
    ForexRevaluationAggregate,
    ForexRevaluationError,
    ForexRevaluationRepository,
    GainLossType,
    InvalidRevaluationStatusError,
    JournalLine,
    RevaluationAlreadyPostedError,
    RevaluationJournal,
    RevaluationResult,
    RevaluationStatus,
)

# Tambahkan import domain events
from domain.forex.domain_events import (
    ForexEventType,
    ForexRateUpdatedEvent,
    ForexRevaluationCompletedEvent,
    ForexTransactionExecutedEvent,
    ForexTransactionRecordedEvent,
)
from domain.forex.exchange_rate_vo import (
    ExchangeRate,
    ExchangeRateError,
    InvalidCurrencyError,
    InvalidEffectiveDateError,
    InvalidRateError,
    calculate_cross_rate,
)
from domain.forex.forex_transaction_entity import (
    ForexTransaction,
    ForexTransactionError,
    ForexTransactionRepository,
    ForexTransactionStatus,
    ForexTransactionType,
)

__all__ = [
    # ExchangeRate
    "ExchangeRate",
    "ExchangeRateError",
    "InvalidCurrencyError",
    "InvalidRateError",
    "InvalidEffectiveDateError",
    "calculate_cross_rate",
    # Aggregate
    "ForexRevaluationAggregate",
    "ForexRevaluationError",
    "ForexRevaluationRepository",
    "GainLossType",
    "InvalidRevaluationStatusError",
    "JournalLine",
    "RevaluationAlreadyPostedError",
    "RevaluationJournal",
    "RevaluationResult",
    "RevaluationStatus",
    # Transaction
    "ForexTransaction",
    "ForexTransactionError",
    "ForexTransactionRepository",
    "ForexTransactionStatus",
    "ForexTransactionType",
    # Domain Events
    "ForexEventType",
    "ForexRateUpdatedEvent",
    "ForexTransactionRecordedEvent",
    "ForexRevaluationCompletedEvent",
    "ForexTransactionExecutedEvent",
]
