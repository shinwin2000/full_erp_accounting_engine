#!/usr/bin/env python3
"""
Module: foreign_currency_translator.py
Layer: Domain / Consolidation
Responsibility: Konversi mata uang asing ke mata uang penyajian.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


class ExchangeRateNotFoundError(Exception):
    """Exception raised when an exchange rate is not available."""

    pass


class ExchangeRateProvider:
    """Protocol/interface for exchange rate providers."""

    async def get_rate(self, from_currency: str, to_currency: str, as_of_date: date) -> Decimal:
        """
        Get exchange rate from one currency to another as of a given date.

        Args:
            from_currency: Source currency code (e.g., "USD")
            to_currency: Target currency code (e.g., "IDR")
            as_of_date: Date for which the rate is valid

        Returns:
            Exchange rate as Decimal (e.g., 15500 for USD/IDR)

        Raises:
            ExchangeRateNotFoundError: If rate is not available
        """
        raise NotImplementedError


class InMemoryExchangeRateProvider(ExchangeRateProvider):
    """Simple in-memory exchange rate provider with fallback to inverse rates."""

    def __init__(self, rates: dict[str, dict[str, Decimal]] | None = None):
        """
        Initialize with optional custom rates.

        Args:
            rates: Nested dict mapping from_currency -> {to_currency: rate}
                   Example: {"USD": {"IDR": Decimal("15500"), "EUR": Decimal("0.92")}}
        """
        self._rates = rates or {
            "USD": {"IDR": Decimal("15500"), "EUR": Decimal("0.92")},
            "EUR": {"IDR": Decimal("16800"), "USD": Decimal("1.08")},
            "IDR": {"USD": Decimal("0.0000645"), "EUR": Decimal("0.0000595")},
        }

    async def get_rate(self, from_currency: str, to_currency: str, as_of_date: date) -> Decimal:
        """
        Get exchange rate from memory. If direct rate not found, tries inverse.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code
            as_of_date: Date (ignored in this implementation, but kept for interface)

        Returns:
            Exchange rate as Decimal

        Raises:
            ExchangeRateNotFoundError: If no rate or inverse rate found
        """
        if from_currency == to_currency:
            return Decimal("1")

        # Try direct rate
        rate = self._rates.get(from_currency, {}).get(to_currency)
        if rate is not None:
            return rate

        # Try inverse rate
        inverse = self._rates.get(to_currency, {}).get(from_currency)
        if inverse is not None:
            return Decimal("1") / inverse

        raise ExchangeRateNotFoundError(
            f"Exchange rate not found: {from_currency} -> {to_currency}"
        )


class ForeignCurrencyTranslator:
    """
    Translator untuk konversi mata uang asing.
    Delegates to an ExchangeRateProvider for actual rates.
    """

    def __init__(self, rate_provider: ExchangeRateProvider | None = None):
        """
        Initialize with optional rate provider.

        Args:
            rate_provider: Provider for exchange rates. If None, uses InMemoryExchangeRateProvider.
        """
        self._rate_provider = rate_provider or InMemoryExchangeRateProvider()
        # For backward compatibility, also keep the old rates dictionaries
        self._rates: dict[str, dict[str, Decimal]] = {
            "USD": {"IDR": Decimal("15500"), "EUR": Decimal("0.92")},
            "EUR": {"IDR": Decimal("16800"), "USD": Decimal("1.08")},
            "IDR": {"USD": Decimal("0.0000645"), "EUR": Decimal("0.0000595")},
        }
        self._avg_rates: dict[str, dict[str, Decimal]] = {
            "USD": {"IDR": Decimal("15400")},
            "EUR": {"IDR": Decimal("16700")},
        }

    async def get_exchange_rate(
        self, from_currency: str, to_currency: str, as_of_date: date
    ) -> Decimal:
        """
        Get exchange rate using the underlying provider.
        """
        return await self._rate_provider.get_rate(from_currency, to_currency, as_of_date)

    async def get_average_rate(
        self, from_currency: str, to_currency: str, as_of_date: date
    ) -> Decimal:
        """
        Get average exchange rate for a period (simplified implementation).
        For real implementation, this would aggregate rates over a period.
        """
        if from_currency == to_currency:
            return Decimal("1")
        rate = self._avg_rates.get(from_currency, {}).get(to_currency)
        if rate is None:
            return await self.get_exchange_rate(from_currency, to_currency, as_of_date)
        return rate


__all__ = [
    "ExchangeRateNotFoundError",
    "ExchangeRateProvider",
    "ForeignCurrencyTranslator",
    "InMemoryExchangeRateProvider",
]
