from __future__ import annotations

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

"""
Package: domain.forex
Foreign exchange revaluation domain.
"""

__all__ = [
    "ExchangeRate",
    "ExchangeRateError",
    "ForexEventType",
    "ForexRateUpdatedEvent",
    "ForexRevaluationAggregate",
    "ForexRevaluationCompletedEvent",
    "ForexRevaluationError",
    "ForexRevaluationRepository",
    "ForexTransaction",
    "ForexTransactionError",
    "ForexTransactionExecutedEvent",
    "ForexTransactionRecordedEvent",
    "ForexTransactionRepository",
    "ForexTransactionStatus",
    "ForexTransactionType",
    "GainLossType",
    "InvalidCurrencyError",
    "InvalidEffectiveDateError",
    "InvalidRateError",
    "InvalidRevaluationStatusError",
    "JournalLine",
    "RevaluationAlreadyPostedError",
    "RevaluationJournal",
    "RevaluationResult",
    "RevaluationStatus",
    "calculate_cross_rate",
]
