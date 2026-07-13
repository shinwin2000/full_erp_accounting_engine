#!/usr/bin/env python3
"""
Module: domain/forex/domain_events.py
Domain events for Forex module.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.event_base import DomainEvent


class ForexEventType(Enum):
    RATE_UPDATED = "rate_updated"
    TRANSACTION_RECORDED = "transaction_recorded"
    REVALUATION_COMPLETED = "revaluation_completed"


class ForexRateUpdatedEvent(DomainEvent):
    """Event ketika nilai tukar diperbarui."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        currency_pair: str,
        old_rate: Decimal,
        new_rate: Decimal,
        updated_by: str,
        **kwargs
    ):
        super().__init__(
            event_type=ForexEventType.RATE_UPDATED.value,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            **kwargs
        )
        self.currency_pair = currency_pair
        self.old_rate = old_rate
        self.new_rate = new_rate
        self.updated_by = updated_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency_pair": self.currency_pair,
            "old_rate": str(self.old_rate),
            "new_rate": str(self.new_rate),
            "updated_by": self.updated_by,
        }


class ForexTransactionRecordedEvent(DomainEvent):
    """Event ketika transaksi forex dicatat."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction_id: UUID,
        from_currency: str,
        to_currency: str,
        amount: Decimal,
        exchange_rate: Decimal,
        recorded_by: str,
        **kwargs
    ):
        super().__init__(
            event_type=ForexEventType.TRANSACTION_RECORDED.value,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            **kwargs
        )
        self.transaction_id = transaction_id
        self.from_currency = from_currency
        self.to_currency = to_currency
        self.amount = amount
        self.exchange_rate = exchange_rate
        self.recorded_by = recorded_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "amount": str(self.amount),
            "exchange_rate": str(self.exchange_rate),
            "recorded_by": self.recorded_by,
        }


class ForexRevaluationCompletedEvent(DomainEvent):
    """Event ketika revaluasi forex selesai."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        revaluation_id: UUID,
        account_id: UUID,
        old_value: Decimal,
        new_value: Decimal,
        revaluation_gain_loss: Decimal,
        completed_by: str,
        **kwargs
    ):
        super().__init__(
            event_type=ForexEventType.REVALUATION_COMPLETED.value,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            **kwargs
        )
        self.revaluation_id = revaluation_id
        self.account_id = account_id
        self.old_value = old_value
        self.new_value = new_value
        self.revaluation_gain_loss = revaluation_gain_loss
        self.completed_by = completed_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "revaluation_id": str(self.revaluation_id),
            "account_id": str(self.account_id),
            "old_value": str(self.old_value),
            "new_value": str(self.new_value),
            "revaluation_gain_loss": str(self.revaluation_gain_loss),
            "completed_by": self.completed_by,
        }


class ForexTransactionExecutedEvent(DomainEvent):
    """Event ketika transaksi forex dieksekusi."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction_id: UUID,
        currency_pair: str,
        amount: Decimal,
        rate: Decimal,
        executed_by: str,
        **kwargs
    ):
        super().__init__(
            event_type="forex_transaction_executed",
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            **kwargs
        )
        self.transaction_id = transaction_id
        self.currency_pair = currency_pair
        self.amount = amount
        self.rate = rate
        self.executed_by = executed_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "currency_pair": self.currency_pair,
            "amount": str(self.amount),
            "rate": str(self.rate),
            "executed_by": self.executed_by,
        }


__all__ = [
    "ForexEventType",
    "ForexRateUpdatedEvent",
    "ForexRevaluationCompletedEvent",
    "ForexTransactionExecutedEvent",
    "ForexTransactionRecordedEvent",
]
