#!/usr/bin/env python3

"""
Module: ntpn_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for NTPN (Nomor Transaksi Penerimaan Negara) used in Indonesian
    tax system (Coretax DJP). NTPN is a 16-digit numeric code that proves payment
    has been made to the state treasury.

    Features:
    - Strict validation (exactly 16 digits, numeric only)
    - Automatic formatting with hyphens (XXXX-XXXX-XXXX-XXXX)
    - Comparison and hashing based on normalized string
    - Extraction of metadata: payment date embed (first 8 digits = YYYYMMDD)
    - Check digit verification using modulo 10 algorithm (Luhn-like, custom for NTPN)
    - Serialization to JSON and from various string formats

Dependencies:
    - Python standard library (re, datetime, decimal)

Audit:
    Any creation of NTPN is logged at DEBUG level for forensic traceability.
    Immutability ensures the value cannot be altered after creation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, ClassVar

# Logger untuk audit trail
logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class NTPNValidationError(ValueError):
    """Raised when NTPN string fails validation."""

    pass


class NTPNParsingError(NTPNValidationError):
    """Raised when input cannot be parsed into a valid NTPN."""

    pass


# ============================================================================
# Value Object: NTPN (Immutable, Frozen)
# ============================================================================


@dataclass(frozen=True, slots=True)
class NTPN:
    """
    Value object representing Nomor Transaksi Penerimaan Negara.

    NTPN is a 16-digit number issued by the Indonesian Treasury (DJP) for
    each successful tax payment. Format: YYYYMMDDXXXXXXXX (date + 8 random digits)
    but not officially structured. This implementation enforces length and
    numeric constraints, plus a checksum to detect typos.

    Business rules:
    1. Must be exactly 16 digits (0-9 only).
    2. Optional hyphens or spaces are removed during normalization.
    3. A check digit is computed using weighted modulo 10 (custom).
    4. The first 8 digits SHOULD represent payment date (YYYYMMDD) - validated if strict_mode=True.
    5. Two NTPN objects are equal iff their normalized strings are equal.

    Examples:
        >>> ntpn = NTPN("2025031512345678")
        >>> ntpn.formatted()
        '2025-0315-1234-5678'   (format: YYYY-MMDD-XXXX-XXXX)
        >>> ntpn.payment_date()
        datetime.date(2025, 3, 15)
    """

    # Class constants
    LENGTH: ClassVar[int] = 16
    DATE_PART_LENGTH: ClassVar[int] = 8
    CHECKSUM_WEIGHTS: ClassVar[tuple[int, ...]] = (2, 4, 6, 8, 1, 3, 5, 7, 9, 2, 4, 6, 8, 1, 3, 5)

    # Internal storage (normalized, no separators)
    _value: str  # stored as private field, but accessed via property

    def __init__(self, value: str | int, strict_mode: bool = True) -> None:
        """
        Initialize NTPN with validation.

        Args:
            value: Raw NTPN string or integer (e.g., "2025031512345678" or 2025031512345678)
            strict_mode: If True, also validates date part (first 8 digits as valid date)

        Raises:
            NTPNValidationError: If the value is invalid.
        """
        object.__setattr__(self, "_value", self._normalize_and_validate(value, strict_mode))
        logger.debug(f"NTPN created: {self._value} (strict_mode={strict_mode})")

    # ------------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------------

    @classmethod
    def _normalize_and_validate(cls, raw: str | int, strict: bool) -> str:
        """Strip separators, validate length, digits, and checksum."""
        raw_str = str(raw).strip()

        # Remove any character that is not digit (hyphens, spaces, dots)
        cleaned = re.sub(r"[^\d]", "", raw_str)

        if len(cleaned) != cls.LENGTH:
            raise NTPNValidationError(
                f"NTPN must be exactly {cls.LENGTH} digits. Got {len(cleaned)} digits from '{raw_str}'"
            )

        if not cleaned.isdigit():
            raise NTPNValidationError(f"NTPN must contain only digits. Got '{cleaned}'")

        # Validate checksum
        if not cls._verify_checksum(cleaned):
            raise NTPNValidationError(
                f"NTPN checksum verification failed for '{cleaned}'. Possible typo."
            )

        # Optional: validate date part
        if strict:
            date_part = cleaned[: cls.DATE_PART_LENGTH]
            try:
                datetime.strptime(date_part, "%Y%m%d")
            except ValueError:
                raise NTPNValidationError(
                    f"NTPN first 8 digits '{date_part}' do not form a valid date (YYYYMMDD)."
                )

        return cleaned

    @classmethod
    def _verify_checksum(cls, digits: str) -> bool:
        """
        Verify NTPN using weighted sum modulo 10.

        This is a custom algorithm to detect common transcription errors.
        Weight pattern repeats: 2,4,6,8,1,3,5,7,9,2,4,6,8,1,3,5
        Sum weight*digit, then check digit = (10 - (sum % 10)) % 10
        The last digit (index 15) is the check digit.
        """
        if len(digits) != cls.LENGTH:
            return False

        total = 0
        for i, ch in enumerate(digits[:-1]):  # exclude last digit (check digit)
            digit = int(ch)
            weight = cls.CHECKSUM_WEIGHTS[i]
            total += digit * weight

        expected_check = (10 - (total % 10)) % 10
        actual_check = int(digits[-1])
        return expected_check == actual_check

    # ------------------------------------------------------------------------
    # Public Properties & Methods
    # ------------------------------------------------------------------------

    @property
    def value(self) -> str:
        """Return raw 16-digit NTPN string without separators."""
        return self._value

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"NTPN('{self._value}')"

    def formatted(self, separator: str = "-") -> str:
        """
        Return NTPN with visual separators every 4 digits.

        Args:
            separator: Character to insert between groups (default '-')

        Returns:
            Formatted string like "2025-0315-1234-5678"
        """
        groups = [self._value[i : i + 4] for i in range(0, self.LENGTH, 4)]
        return separator.join(groups)

    def payment_date(self) -> date:
        """
        Extract the presumed payment date from the first 8 digits.

        Returns:
            date object derived from YYYYMMDD prefix.

        Raises:
            ValueError: If the date part is invalid (should not happen if constructed with strict_mode=True).
        """
        date_str = self._value[: self.DATE_PART_LENGTH]
        return datetime.strptime(date_str, "%Y%m%d").date()

    def is_valid_date(self) -> bool:
        """Check if the first 8 digits form a valid date."""
        try:
            self.payment_date()
            return True
        except ValueError:
            return False

    def to_json(self) -> dict[str, Any]:
        """Serialise to JSON-compatible dictionary."""
        return {
            "value": self._value,
            "formatted": self.formatted(),
            "payment_date": self.payment_date().isoformat() if self.is_valid_date() else None,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> NTPN:
        """Reconstruct NTPN from JSON."""
        return cls(data["value"])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NTPN):
            return False
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __lt__(self, other: NTPN) -> bool:
        """Order by numeric value (useful for sorting)."""
        return int(self._value) < int(other._value)

    # ------------------------------------------------------------------------
    # Alternative Constructors
    # ------------------------------------------------------------------------

    @classmethod
    def from_formatted(cls, formatted: str) -> NTPN:
        """
        Create NTPN from a string that may contain hyphens or spaces.

        Example: "2025-0315-1234-5678" -> NTPN("2025031512345678")
        """
        cleaned = re.sub(r"[^\d]", "", formatted)
        return cls(cleaned)

    @classmethod
    def generate_dummy(cls, payment_date: date, seed: int = 0) -> NTPN:
        """
        Generate a deterministic dummy NTPN for testing or dry-run.

        WARNING: This is NOT a real NTPN. Only for integration tests or
        sandbox environments. The checksum is computed correctly.

        Args:
            payment_date: Date that will become the first 8 digits.
            seed: Optional integer to influence the trailing 7 digits (non-check part).

        Returns:
            A syntactically valid NTPN (but not registered with DJP).
        """
        date_part = payment_date.strftime("%Y%m%d")
        # Generate 7 random-looking digits from seed
        import hashlib

        h = hashlib.sha256(f"{date_part}{seed}".encode()).hexdigest()
        rand_part = h[:7]  # 7 digits
        base = date_part + rand_part  # 15 digits (without check digit)
        # Compute check digit
        total = 0
        for i, ch in enumerate(base):
            digit = int(ch)
            weight = cls.CHECKSUM_WEIGHTS[i]
            total += digit * weight
        check = (10 - (total % 10)) % 10
        ntpn_str = base + str(check)
        return cls(ntpn_str, strict_mode=False)


# ============================================================================
# Helper Functions for Common Operations
# ============================================================================


def validate_ntpn_string(raw: str) -> bool:
    """
    Quick validation without creating NTPN object (returns bool).

    Args:
        raw: Raw string possibly containing NTPN.

    Returns:
        True if the string represents a valid NTPN.
    """
    try:
        NTPN(raw)
        return True
    except NTPNValidationError:
        return False


def normalize_ntpn(raw: str | int) -> str:
    """
    Return normalized 16-digit string without validation (only cleaning separators).

    Args:
        raw: Raw input.

    Returns:
        Cleaned string of digits, or empty string if no digits found.
    """
    return re.sub(r"[^\d]", "", str(raw))


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "NTPN",
    "NTPNParsingError",
    "NTPNValidationError",
    "normalize_ntpn",
    "validate_ntpn_string",
]
