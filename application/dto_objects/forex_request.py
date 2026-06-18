# forex_request.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: forex_request.py
Layer: Application / DTO Objects
Responsibility: Data Transfer Objects untuk operasi foreign exchange (forex).

Fitur:
- Forex revaluation request
- Exchange rate request
- Currency conversion
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class ForexRevaluationRequest:
    """DTO untuk request revaluasi mata uang asing."""

    legal_entity_id: UUID
    currency: str
    balance_in_fcy: Decimal
    account_code: str
    as_of_date: date
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be a 3-letter ISO code")
        if self.balance_in_fcy <= 0:
            raise ValueError(f"Balance in foreign currency must be positive: {self.balance_in_fcy}")
        if not self.account_code:
            raise ValueError("Account code is required")

    @property
    def is_gain(self) -> bool:
        """Placeholder - actual gain/loss depends on exchange rate movement."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "currency": self.currency,
            "balance_in_fcy": str(self.balance_in_fcy),
            "account_code": self.account_code,
            "as_of_date": self.as_of_date.isoformat(),
            "description": self.description,
        }


@dataclass(kw_only=True)
class ForexRateRequest:
    """DTO untuk request kurs mata uang."""

    from_currency: str
    to_currency: str
    rate_date: date | None = None

    def __post_init__(self) -> None:
        if not self.from_currency or len(self.from_currency) != 3:
            raise ValueError("from_currency must be a 3-letter ISO code")
        if not self.to_currency or len(self.to_currency) != 3:
            raise ValueError("to_currency must be a 3-letter ISO code")
        if self.from_currency == self.to_currency:
            raise ValueError("from_currency and to_currency cannot be the same")

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate_date": self.rate_date.isoformat() if self.rate_date else None,
        }


@dataclass(kw_only=True)
class ForexConversionRequest:
    """DTO untuk request konversi mata uang."""

    amount: Decimal
    from_currency: str
    to_currency: str
    rate_date: date | None = None
    legal_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive: {self.amount}")
        if not self.from_currency or len(self.from_currency) != 3:
            raise ValueError("from_currency must be a 3-letter ISO code")
        if not self.to_currency or len(self.to_currency) != 3:
            raise ValueError("to_currency must be a 3-letter ISO code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate_date": self.rate_date.isoformat() if self.rate_date else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


__all__ = [
    "ForexConversionRequest",
    "ForexRateRequest",
    "ForexRevaluationRequest",
]
