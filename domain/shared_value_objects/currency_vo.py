#!/usr/bin/env python3
"""
Module: currency_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for currency (ISO 4217). Immutable.
    Represents a currency with code, numeric code, name, symbol, decimal places,
    and provides formatting and conversion utilities.

Business rules:
    - Currency code must be a valid ISO 4217 three-letter code (e.g., IDR, USD, EUR).
    - Each currency has a fixed number of decimal places (0-3).
    - The value object is immutable and hashable.
    - Supports formatting amounts with proper decimal places and symbol.
    - Supports currency conversion via exchange rate (delegated to ExchangeRateVO).

Dependencies:
    - Standard library (decimal, dataclass, enum, typing)
    - decimal for precise arithmetic

Audit:
    Every usage of currency should be traceable. The value object itself is pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

# ============================================================================
# Currency Code Enum (ISO 4217)
# ============================================================================


class CurrencyCode(Enum):
    """ISO 4217 currency codes supported by the system."""

    # Major currencies
    IDR = "IDR"  # Indonesian Rupiah
    USD = "USD"  # US Dollar
    EUR = "EUR"  # Euro
    GBP = "GBP"  # British Pound Sterling
    JPY = "JPY"  # Japanese Yen
    CNY = "CNY"  # Chinese Yuan Renminbi
    SGD = "SGD"  # Singapore Dollar
    MYR = "MYR"  # Malaysian Ringgit
    THB = "THB"  # Thai Baht
    VND = "VND"  # Vietnamese Dong
    PHP = "PHP"  # Philippine Peso
    AUD = "AUD"  # Australian Dollar
    CAD = "CAD"  # Canadian Dollar
    CHF = "CHF"  # Swiss Franc
    NZD = "NZD"  # New Zealand Dollar
    KRW = "KRW"  # South Korean Won
    INR = "INR"  # Indian Rupee
    SAR = "SAR"  # Saudi Riyal
    AED = "AED"  # UAE Dirham
    ZAR = "ZAR"  # South African Rand
    RUB = "RUB"  # Russian Ruble
    BRL = "BRL"  # Brazilian Real
    MXN = "MXN"  # Mexican Peso
    TRY = "TRY"  # Turkish Lira
    SEK = "SEK"  # Swedish Krona
    NOK = "NOK"  # Norwegian Krone
    DKK = "DKK"  # Danish Krone
    PLN = "PLN"  # Polish Zloty
    HKD = "HKD"  # Hong Kong Dollar
    TWD = "TWD"  # New Taiwan Dollar

    # Added currencies for three-decimal support
    KWD = "KWD"  # Kuwaiti Dinar
    BHD = "BHD"  # Bahraini Dinar
    OMR = "OMR"  # Omani Rial
    JOD = "JOD"  # Jordanian Dinar

    @classmethod
    def from_string(cls, code: str) -> CurrencyCode | None:
        """Parse currency code from string (case-insensitive)."""
        code_upper = code.upper().strip()
        for currency in cls:
            if currency.value == code_upper:
                return currency
        return None

    @classmethod
    def is_supported(cls, code: str) -> bool:
        """Check if a currency code is supported."""
        return cls.from_string(code) is not None


# ============================================================================
# Currency Value Object
# ============================================================================


@dataclass(frozen=True)
class CurrencyVO:
    """
    Immutable value object representing a currency.

    Attributes:
        code: ISO 4217 three-letter currency code (CurrencyCode enum)

    Examples:
        >>> idr = CurrencyVO(CurrencyCode.IDR)
        >>> idr.format(Decimal('1500000.50'))
        'Rp 1.500.001'
        >>> usd = CurrencyVO.from_code('USD')
        >>> usd.symbol
        '$'
    """

    code: CurrencyCode

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Full English name of the currency."""
        names = {
            CurrencyCode.IDR: "Indonesian Rupiah",
            CurrencyCode.USD: "United States Dollar",
            CurrencyCode.EUR: "Euro",
            CurrencyCode.GBP: "Pound Sterling",
            CurrencyCode.JPY: "Japanese Yen",
            CurrencyCode.CNY: "Chinese Yuan Renminbi",
            CurrencyCode.SGD: "Singapore Dollar",
            CurrencyCode.MYR: "Malaysian Ringgit",
            CurrencyCode.THB: "Thai Baht",
            CurrencyCode.VND: "Vietnamese Dong",
            CurrencyCode.PHP: "Philippine Peso",
            CurrencyCode.AUD: "Australian Dollar",
            CurrencyCode.CAD: "Canadian Dollar",
            CurrencyCode.CHF: "Swiss Franc",
            CurrencyCode.NZD: "New Zealand Dollar",
            CurrencyCode.KRW: "South Korean Won",
            CurrencyCode.INR: "Indian Rupee",
            CurrencyCode.SAR: "Saudi Riyal",
            CurrencyCode.AED: "UAE Dirham",
            CurrencyCode.ZAR: "South African Rand",
            CurrencyCode.RUB: "Russian Ruble",
            CurrencyCode.BRL: "Brazilian Real",
            CurrencyCode.MXN: "Mexican Peso",
            CurrencyCode.TRY: "Turkish Lira",
            CurrencyCode.SEK: "Swedish Krona",
            CurrencyCode.NOK: "Norwegian Krone",
            CurrencyCode.DKK: "Danish Krone",
            CurrencyCode.PLN: "Polish Zloty",
            CurrencyCode.HKD: "Hong Kong Dollar",
            CurrencyCode.TWD: "New Taiwan Dollar",
            CurrencyCode.KWD: "Kuwaiti Dinar",
            CurrencyCode.BHD: "Bahraini Dinar",
            CurrencyCode.OMR: "Omani Rial",
            CurrencyCode.JOD: "Jordanian Dinar",
        }
        return names.get(self.code, self.code.value)

    @property
    def symbol(self) -> str:
        """Currency symbol (e.g., '$', '€', 'Rp')."""
        symbols = {
            CurrencyCode.IDR: "Rp",
            CurrencyCode.USD: "$",
            CurrencyCode.EUR: "€",
            CurrencyCode.GBP: "£",
            CurrencyCode.JPY: "¥",
            CurrencyCode.CNY: "¥",
            CurrencyCode.SGD: "S$",
            CurrencyCode.MYR: "RM",
            CurrencyCode.THB: "฿",
            CurrencyCode.VND: "₫",
            CurrencyCode.PHP: "₱",
            CurrencyCode.AUD: "A$",
            CurrencyCode.CAD: "C$",
            CurrencyCode.CHF: "Fr",
            CurrencyCode.NZD: "NZ$",
            CurrencyCode.KRW: "₩",
            CurrencyCode.INR: "₹",
            CurrencyCode.SAR: "﷼",
            CurrencyCode.AED: "د.إ",
            CurrencyCode.ZAR: "R",
            CurrencyCode.RUB: "₽",
            CurrencyCode.BRL: "R$",
            CurrencyCode.MXN: "$",
            CurrencyCode.TRY: "₺",
            CurrencyCode.SEK: "kr",
            CurrencyCode.NOK: "kr",
            CurrencyCode.DKK: "kr",
            CurrencyCode.PLN: "zł",
            CurrencyCode.HKD: "HK$",
            CurrencyCode.TWD: "NT$",
            CurrencyCode.KWD: "KD",
            CurrencyCode.BHD: "BD",
            CurrencyCode.OMR: "OMR",
            CurrencyCode.JOD: "JD",
        }
        return symbols.get(self.code, self.code.value)

    @property
    def numeric_code(self) -> int:
        """ISO 4217 numeric code (3 digits)."""
        numeric = {
            CurrencyCode.IDR: 360,
            CurrencyCode.USD: 840,
            CurrencyCode.EUR: 978,
            CurrencyCode.GBP: 826,
            CurrencyCode.JPY: 392,
            CurrencyCode.CNY: 156,
            CurrencyCode.SGD: 702,
            CurrencyCode.MYR: 458,
            CurrencyCode.THB: 764,
            CurrencyCode.VND: 704,
            CurrencyCode.PHP: 608,
            CurrencyCode.AUD: 36,
            CurrencyCode.CAD: 124,
            CurrencyCode.CHF: 756,
            CurrencyCode.NZD: 554,
            CurrencyCode.KRW: 410,
            CurrencyCode.INR: 356,
            CurrencyCode.SAR: 682,
            CurrencyCode.AED: 784,
            CurrencyCode.ZAR: 710,
            CurrencyCode.RUB: 643,
            CurrencyCode.BRL: 986,
            CurrencyCode.MXN: 484,
            CurrencyCode.TRY: 949,
            CurrencyCode.SEK: 752,
            CurrencyCode.NOK: 578,
            CurrencyCode.DKK: 208,
            CurrencyCode.PLN: 985,
            CurrencyCode.HKD: 344,
            CurrencyCode.TWD: 901,
            CurrencyCode.KWD: 414,
            CurrencyCode.BHD: 48,
            CurrencyCode.OMR: 512,
            CurrencyCode.JOD: 400,
        }
        return numeric.get(self.code, 0)

    @property
    def decimal_places(self) -> int:
        """Number of decimal places for this currency (0, 2, or 3)."""
        # Most currencies use 2 decimals
        zero_decimal = {CurrencyCode.JPY, CurrencyCode.KRW, CurrencyCode.VND}
        three_decimal = {CurrencyCode.KWD, CurrencyCode.BHD, CurrencyCode.OMR, CurrencyCode.JOD}
        if self.code in zero_decimal:
            return 0
        elif self.code in three_decimal:
            return 3
        else:
            return 2

    @property
    def minor_unit_name(self) -> str:
        """Name of the minor unit (e.g., 'sen' for IDR, 'cent' for USD)."""
        minor_names = {
            CurrencyCode.IDR: "sen",
            CurrencyCode.USD: "cent",
            CurrencyCode.EUR: "cent",
            CurrencyCode.GBP: "penny",
            CurrencyCode.JPY: "sen",
            CurrencyCode.CNY: "fen",
            CurrencyCode.SGD: "cent",
            CurrencyCode.MYR: "sen",
            CurrencyCode.THB: "satang",
            CurrencyCode.VND: "xu",
            CurrencyCode.PHP: "sentimo",
            CurrencyCode.AUD: "cent",
            CurrencyCode.CAD: "cent",
            CurrencyCode.CHF: "rappen",
            CurrencyCode.NZD: "cent",
            CurrencyCode.KRW: "jeon",
            CurrencyCode.INR: "paisa",
            CurrencyCode.SAR: "halala",
            CurrencyCode.AED: "fils",
            CurrencyCode.ZAR: "cent",
            CurrencyCode.RUB: "kopek",
            CurrencyCode.BRL: "centavo",
            CurrencyCode.MXN: "centavo",
            CurrencyCode.TRY: "kuruş",
            CurrencyCode.SEK: "öre",
            CurrencyCode.NOK: "øre",
            CurrencyCode.DKK: "øre",
            CurrencyCode.PLN: "grosz",
            CurrencyCode.HKD: "cent",
            CurrencyCode.TWD: "cent",
            CurrencyCode.KWD: "fils",
            CurrencyCode.BHD: "fils",
            CurrencyCode.OMR: "baisa",
            CurrencyCode.JOD: "piastre",
        }
        return minor_names.get(self.code, "cent")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_code(cls, code: str) -> CurrencyVO | None:
        """Create CurrencyVO from a string currency code."""
        currency_code = CurrencyCode.from_string(code)
        if currency_code is None:
            return None
        return cls(currency_code)

    @classmethod
    def from_numeric(cls, numeric: int) -> CurrencyVO | None:
        """Create CurrencyVO from ISO numeric code."""
        for code in CurrencyCode:
            if cls(code).numeric_code == numeric:
                return cls(code)
        return None

    @classmethod
    def default_currency(cls) -> CurrencyVO:
        """Return the system default currency (IDR)."""
        return cls(CurrencyCode.IDR)

    # ------------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------------

    def format(
        self,
        amount: Decimal,
        include_symbol: bool = True,
        include_currency_code: bool = False,
        group_separator: str = ".",
        decimal_separator: str = ",",
    ) -> str:
        """
        Format a Decimal amount with this currency.

        Args:
            amount: The amount to format
            include_symbol: Include currency symbol (e.g., '$')
            include_currency_code: Include ISO code (e.g., 'USD')
            group_separator: Thousands separator (default '.')
            decimal_separator: Decimal point separator (default ',')

        Returns:
            Formatted string like 'Rp 1.500.000,00' or '1,500.00 USD'
        """
        quantize = (
            Decimal(f"1.{'0' * self.decimal_places}") if self.decimal_places > 0 else Decimal("1")
        )
        rounded = amount.quantize(quantize, rounding=ROUND_HALF_EVEN)

        # Format number part
        if self.decimal_places == 0:
            number_str = f"{int(rounded):,}".replace(",", group_separator)
        else:
            integer_part = int(abs(rounded))
            fractional_part = f"{abs(rounded):.{self.decimal_places}f}".split(".")[1]
            integer_str = f"{integer_part:,}".replace(",", group_separator)
            number_str = f"{integer_str}{decimal_separator}{fractional_part}"

        # Add negative sign if needed
        if rounded < 0:
            number_str = f"-{number_str}"

        # Assemble result
        result_parts = []
        if include_symbol:
            result_parts.append(self.symbol)
        result_parts.append(number_str)
        if include_currency_code:
            result_parts.append(self.code.value)

        return " ".join(result_parts).strip()

    def to_minor_units(self, amount: Decimal) -> int:
        """
        Convert a Decimal amount to the smallest minor unit (e.g., cents, sen).

        Example: USD 1.23 -> 123 cents, JPY 100 -> 100 (no minor units)
        """
        multiplier = 10**self.decimal_places
        return int(amount * multiplier)

    def from_minor_units(self, minor_units: int) -> Decimal:
        """Convert from minor units (e.g., cents) to Decimal."""
        multiplier = 10**self.decimal_places
        return Decimal(minor_units) / Decimal(multiplier)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "code": self.code.value,
            "numeric_code": self.numeric_code,
            "name": self.name,
            "symbol": self.symbol,
            "decimal_places": self.decimal_places,
            "minor_unit_name": self.minor_unit_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurrencyVO:
        """Reconstruct from dict. Raises ValueError if code is invalid."""
        currency = cls.from_code(data["code"])
        if currency is None:
            raise ValueError(f"Invalid currency code: {data['code']}")
        return currency

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.code.value

    def __repr__(self) -> str:
        return f"CurrencyVO('{self.code.value}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CurrencyVO):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)


# ============================================================================
# Type alias for convenience
# ============================================================================

Currency = CurrencyVO

# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "Currency",
    "CurrencyCode",
    "CurrencyVO",
]
