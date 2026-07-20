#!/usr/bin/env python3
"""
Module: supplier_withholding_category_vo.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Value object for PPh withholding category (Pasal 21, 22, 23, 26, 4(2)).
    Immutable. Determines the tax withholding rules for payments to suppliers.

Business rules:
    - Article determines the type of withholding tax.
    - Rate must be between 0 and 100 (percentage).
    - For article NONE, rate must be 0.
    - Final tax (is_final) means no further tax calculation.
    - Provides methods to calculate withholding amount.
    - Supports multiple special rates based on transaction type.
    - Immutable: all changes create new instances.

Dependencies:
    - Python standard library (decimal, dataclass, enum, typing, datetime)

Audit:
    Pure value object; no I/O. Caller should log withholding category changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class WithholdingArticle(Enum):
    """PPh withholding article for supplier payments."""

    NONE = "none"  # No withholding
    PPH_21 = "21"  # PPh Pasal 21 (for services from individuals)
    PPH_22 = "22"  # PPh Pasal 22 (imports, purchases)
    PPH_23 = "23"  # PPh Pasal 23 (services, rent, royalties)
    PPH_26 = "26"  # PPh Pasal 26 (foreign entities)
    PPH_4_2 = "4(2)"  # PPh Pasal 4 ayat 2 (final)

    def display_name(self) -> str:
        names = {
            WithholdingArticle.NONE: "Tidak Dipotong",
            WithholdingArticle.PPH_21: "PPh Pasal 21",
            WithholdingArticle.PPH_22: "PPh Pasal 22",
            WithholdingArticle.PPH_23: "PPh Pasal 23",
            WithholdingArticle.PPH_26: "PPh Pasal 26",
            WithholdingArticle.PPH_4_2: "PPh Pasal 4(2) Final",
        }
        return names.get(self, self.value)

    def is_final_by_default(self) -> bool:
        """Check if this article is typically final tax."""
        return self == WithholdingArticle.PPH_4_2

    def requires_npwp(self) -> bool:
        """Check if this article requires supplier NPWP."""
        return self not in (WithholdingArticle.NONE,)

    def requires_invoice(self) -> bool:
        """Check if this article requires a tax invoice."""
        return self in (WithholdingArticle.PPH_22, WithholdingArticle.PPH_23)

    @classmethod
    def from_string(cls, value: str) -> WithholdingArticle | None:
        value_lower = value.lower().strip()
        if value_lower in ("none", "0", "tidak"):
            return WithholdingArticle.NONE
        if value_lower in ("21", "pph21", "pph 21"):
            return WithholdingArticle.PPH_21
        if value_lower in ("22", "pph22", "pph 22"):
            return WithholdingArticle.PPH_22
        if value_lower in ("23", "pph23", "pph 23"):
            return WithholdingArticle.PPH_23
        if value_lower in ("26", "pph26", "pph 26"):
            return WithholdingArticle.PPH_26
        if value_lower in ("4(2)", "42", "pph42", "pph 4(2)"):
            return WithholdingArticle.PPH_4_2
        return None


class WithholdingRate(Enum):
    """Standard PPh withholding rates (for reference, not used for calculation)."""

    RATE_0 = 0
    RATE_0_5 = 0.5
    RATE_1 = 1
    RATE_1_5 = 1.5
    RATE_2 = 2
    RATE_2_5 = 2.5
    RATE_3 = 3
    RATE_4 = 4
    RATE_5 = 5
    RATE_6 = 6
    RATE_10 = 10
    RATE_15 = 15
    RATE_20 = 20
    RATE_25 = 25

    def as_decimal(self) -> Decimal:
        return Decimal(str(self.value))

    def display_name(self) -> str:
        return f"{self.value}%"


# ============================================================================
# Exceptions
# ============================================================================


class WithholdingCategoryError(ValueError):
    """Base exception for withholding category errors."""
    pass


class InvalidWithholdingRateError(WithholdingCategoryError):
    """Raised when rate is invalid for the given article."""
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_rate(rate: Decimal, article: WithholdingArticle) -> Decimal:
    """Validate rate is between 0 and 100 and round to 2 decimal places."""
    if rate < 0 or rate > 100:
        raise InvalidWithholdingRateError(f"Rate must be between 0 and 100, got {rate}")
    if article == WithholdingArticle.NONE and rate != 0:
        raise InvalidWithholdingRateError(f"Rate must be 0 for article NONE, got {rate}")
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


# ============================================================================
# Value Object: SupplierWithholdingCategoryVO
# ============================================================================


@dataclass(frozen=True)
class SupplierWithholdingCategoryVO:
    """
    Immutable value object for PPh withholding category.

    Attributes:
        article: WithholdingArticle enum
        rate: Withholding rate (as Decimal, 0-100)
        is_final: Whether the tax is final (no further calculation)
        effective_date: Date when this category becomes effective
        notes: Additional notes
        special_rates: Dict of transaction type to custom rate (Decimal)

    Examples:
        >>> category = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal('2'))
        >>> category.should_withhold
        True
        >>> category.calculate_withholding(Decimal('10000000'))
        Decimal('200000.00')
        >>> category.to_dict()
        {...}
    """

    article: WithholdingArticle
    rate: Decimal
    is_final: bool = False
    effective_date: date | None = None
    notes: str = ""
    special_rates: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate withholding category."""
        if not isinstance(self.article, WithholdingArticle):
            raise WithholdingCategoryError(f"Invalid article: {self.article}")

        # Validate rate (ensure Decimal)
        if not isinstance(self.rate, Decimal):
            raise WithholdingCategoryError(f"rate must be Decimal, got {type(self.rate).__name__}")
        normalized_rate = _validate_rate(self.rate, self.article)
        if normalized_rate != self.rate:
            object.__setattr__(self, "rate", normalized_rate)

        # Set is_final default based on article if not explicitly set
        if not self.is_final and self.article.is_final_by_default():
            object.__setattr__(self, "is_final", True)

        # Validate effective_date
        if self.effective_date is not None and self.effective_date > date.today():
            raise WithholdingCategoryError("Effective date cannot be in the future")

        # Clean notes
        if self.notes:
            object.__setattr__(self, "notes", self.notes.strip())

        # Validate special_rates values
        for txn_type, sp_rate in self.special_rates.items():
            if not isinstance(sp_rate, Decimal):
                raise WithholdingCategoryError(
                    f"Special rate for {txn_type} must be Decimal, got {type(sp_rate).__name__}"
                )
            if sp_rate < 0 or sp_rate > 100:
                raise InvalidWithholdingRateError(
                    f"Special rate for {txn_type} must be 0-100, got {sp_rate}"
                )

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_none(cls, notes: str = "") -> SupplierWithholdingCategoryVO:
        """Create a category with no withholding."""
        return cls(
            article=WithholdingArticle.NONE,
            rate=Decimal("0"),
            is_final=False,
            notes=notes or "No withholding",
        )

    @classmethod
    def create_pph21(
        cls, rate: Decimal = Decimal("5"), is_final: bool = False
    ) -> SupplierWithholdingCategoryVO:
        """Create PPh Pasal 21 category."""
        return cls(
            article=WithholdingArticle.PPH_21,
            rate=rate,
            is_final=is_final,
            notes="PPh Pasal 21 - Jasa Perorangan",
        )

    @classmethod
    def create_pph22(
        cls, rate: Decimal = Decimal("1.5"), is_final: bool = False
    ) -> SupplierWithholdingCategoryVO:
        """Create PPh Pasal 22 category."""
        return cls(
            article=WithholdingArticle.PPH_22,
            rate=rate,
            is_final=is_final,
            notes="PPh Pasal 22 - Impor/Pembelian",
        )

    @classmethod
    def create_pph23(
        cls, rate: Decimal = Decimal("2"), is_final: bool = False
    ) -> SupplierWithholdingCategoryVO:
        """Create PPh Pasal 23 category."""
        return cls(
            article=WithholdingArticle.PPH_23,
            rate=rate,
            is_final=is_final,
            notes="PPh Pasal 23 - Jasa/Sewa/Royalti",
        )

    @classmethod
    def create_pph26(
        cls, rate: Decimal = Decimal("20"), is_final: bool = False
    ) -> SupplierWithholdingCategoryVO:
        """Create PPh Pasal 26 category for foreign entities."""
        return cls(
            article=WithholdingArticle.PPH_26,
            rate=rate,
            is_final=is_final,
            notes="PPh Pasal 26 - WPLN",
        )

    @classmethod
    def create_pph4_2(
        cls, rate: Decimal = Decimal("10"), is_final: bool = True
    ) -> SupplierWithholdingCategoryVO:
        """Create PPh Pasal 4 ayat 2 final category."""
        return cls(
            article=WithholdingArticle.PPH_4_2,
            rate=rate,
            is_final=True,
            notes="PPh Pasal 4(2) Final",
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupplierWithholdingCategoryVO:
        """Reconstruct from dictionary."""
        article = WithholdingArticle.from_string(data.get("article", "none"))
        if article is None:
            article = WithholdingArticle.NONE
        rate = Decimal(str(data.get("rate", 0)))
        is_final = data.get("is_final", article.is_final_by_default())
        effective_date = data.get("effective_date")
        if isinstance(effective_date, str):
            effective_date = date.fromisoformat(effective_date)
        special_rates = data.get("special_rates", {})
        if special_rates:
            special_rates = {k: Decimal(str(v)) for k, v in special_rates.items()}
        return cls(
            article=article,
            rate=rate,
            is_final=is_final,
            effective_date=effective_date,
            notes=data.get("notes", ""),
            special_rates=special_rates,
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def should_withhold(self) -> bool:
        """Whether withholding should be applied."""
        return self.article != WithholdingArticle.NONE and self.rate > 0

    @property
    def rate_percentage(self) -> float:
        """Rate as float percentage (for display only, not for calculation)."""
        return float(self.rate)

    @property
    def rate_decimal(self) -> Decimal:
        """Rate as Decimal factor (rate / 100)."""
        return self.rate / Decimal("100")

    @property
    def display_name(self) -> str:
        """Full display name with rate."""
        if not self.should_withhold:
            return self.article.display_name()
        return f"{self.article.display_name()} - {self.rate}%"

    # ------------------------------------------------------------------------
    # Business Logic
    # ------------------------------------------------------------------------

    def calculate_withholding(self, amount: Decimal, transaction_type: str = "default") -> Decimal:
        """
        Calculate withholding amount.

        Args:
            amount: Gross amount (positive Decimal)
            transaction_type: Type of transaction ('service', 'rental', 'royalty', 'import', 'default')

        Returns:
            Withholding amount (rounded to nearest currency unit)
        """
        if not self.should_withhold:
            return Decimal("0")
        if amount < 0:
            raise ValueError(f"Amount cannot be negative: {amount}")

        # Check for special rate based on transaction type
        rate = self.special_rates.get(transaction_type, self.rate)
        result = amount * rate / Decimal("100")
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def is_applicable(self, transaction_date: date | None = None) -> bool:
        """Check if this category is applicable on the given date."""
        if self.effective_date is None:
            return True
        check_date = transaction_date or date.today()
        return check_date >= self.effective_date

    def with_rate(
        self, new_rate: Decimal, updated_by: str = "system"
    ) -> SupplierWithholdingCategoryVO:
        """Create a new category with updated rate."""
        return SupplierWithholdingCategoryVO(
            article=self.article,
            rate=new_rate,
            is_final=self.is_final,
            effective_date=date.today(),
            notes=f"{self.notes} | Rate changed from {self.rate} to {new_rate} by {updated_by}",
            special_rates=self.special_rates,
        )

    def with_article(
        self, new_article: WithholdingArticle, updated_by: str = "system"
    ) -> SupplierWithholdingCategoryVO:
        """Create a new category with updated article."""
        default_rates = {
            WithholdingArticle.PPH_21: Decimal("5"),
            WithholdingArticle.PPH_22: Decimal("1.5"),
            WithholdingArticle.PPH_23: Decimal("2"),
            WithholdingArticle.PPH_26: Decimal("20"),
            WithholdingArticle.PPH_4_2: Decimal("10"),
            WithholdingArticle.NONE: Decimal("0"),
        }
        new_rate = default_rates.get(new_article, Decimal("0"))
        return SupplierWithholdingCategoryVO(
            article=new_article,
            rate=new_rate,
            is_final=new_article.is_final_by_default(),
            effective_date=date.today(),
            notes=f"{self.notes} | Article changed from {self.article.value} to {new_article.value} by {updated_by}",
            special_rates=self.special_rates,
        )

    def add_special_rate(
        self, transaction_type: str, rate: Decimal
    ) -> SupplierWithholdingCategoryVO:
        """Add or update special rate for a transaction type."""
        if rate < 0 or rate > 100:
            raise InvalidWithholdingRateError(f"Rate must be 0-100, got {rate}")
        new_special = dict(self.special_rates)
        new_special[transaction_type] = rate
        return SupplierWithholdingCategoryVO(
            article=self.article,
            rate=self.rate,
            is_final=self.is_final,
            effective_date=self.effective_date,
            notes=f"{self.notes} | Added special rate {rate}% for {transaction_type}",
            special_rates=new_special,
        )

    def remove_special_rate(self, transaction_type: str) -> SupplierWithholdingCategoryVO:
        """Remove special rate for a transaction type."""
        if transaction_type not in self.special_rates:
            return self
        new_special = dict(self.special_rates)
        del new_special[transaction_type]
        return SupplierWithholdingCategoryVO(
            article=self.article,
            rate=self.rate,
            is_final=self.is_final,
            effective_date=self.effective_date,
            notes=f"{self.notes} | Removed special rate for {transaction_type}",
            special_rates=new_special,
        )

    def effective_from(self, new_date: date) -> SupplierWithholdingCategoryVO:
        """Change effective date."""
        return SupplierWithholdingCategoryVO(
            article=self.article,
            rate=self.rate,
            is_final=self.is_final,
            effective_date=new_date,
            notes=self.notes,
            special_rates=self.special_rates,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "article": self.article.value,
            "article_display": self.article.display_name(),
            "rate": str(self.rate),
            "rate_percentage": self.rate_percentage,
            "is_final": self.is_final,
            "should_withhold": self.should_withhold,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "notes": self.notes,
            "special_rates": {k: str(v) for k, v in self.special_rates.items()},
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "withholding_article": self.article.value,
            "withholding_rate": self.rate,
            "withholding_is_final": self.is_final,
            "withholding_effective_date": self.effective_date,
            "withholding_notes": self.notes,
            "withholding_special_rates": ",".join(
                [f"{k}:{v}" for k, v in self.special_rates.items()]
            )
            if self.special_rates
            else None,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.display_name

    def __repr__(self) -> str:
        return f"SupplierWithholdingCategoryVO(article={self.article.value}, rate={self.rate}, final={self.is_final})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SupplierWithholdingCategoryVO):
            return False
        return (
            self.article == other.article
            and self.rate == other.rate
            and self.is_final == other.is_final
            and self.effective_date == other.effective_date
        )

    def __hash__(self) -> int:
        return hash((self.article, self.rate, self.is_final, self.effective_date))


# ============================================================================
# Helper Functions
# ============================================================================


def get_default_withholding_for_transaction(transaction_type: str) -> SupplierWithholdingCategoryVO:
    """Get default withholding category based on transaction type."""
    defaults = {
        "service": SupplierWithholdingCategoryVO.create_pph23(Decimal("2")),
        "rental": SupplierWithholdingCategoryVO.create_pph23(Decimal("10")),
        "royalty": SupplierWithholdingCategoryVO.create_pph23(Decimal("15")),
        "import": SupplierWithholdingCategoryVO.create_pph22(Decimal("7.5")),
        "construction": SupplierWithholdingCategoryVO.create_pph4_2(Decimal("2")),
    }
    return defaults.get(transaction_type, SupplierWithholdingCategoryVO.create_none())


def calculate_withholding_for_supplier(
    supplier_category: SupplierWithholdingCategoryVO,
    amount: Decimal,
    transaction_type: str = "default",
) -> Decimal:
    """Convenience function to calculate withholding."""
    return supplier_category.calculate_withholding(amount, transaction_type)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvalidWithholdingRateError",
    "SupplierWithholdingCategoryVO",
    "WithholdingArticle",
    "WithholdingCategoryError",
    "WithholdingRate",
    "calculate_withholding_for_supplier",
    "get_default_withholding_for_transaction",
]
