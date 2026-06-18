#!/usr/bin/env python3
"""
Module: customer_credit_limit_vo.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Value object for customer credit limit. Immutable.
    Represents the maximum credit amount extended to a customer, including
    currency, effective date range, approval information, and usage tracking.

Business rules:
    - Credit limit amount must be >= 0.
    - Currency must be a valid ISO 4217 code (default 'IDR').
    - Effective date must be <= expiry date (if expiry provided).
    - Only active (non-expired) credit limits are applicable.
    - Multiple credit limit revisions can be tracked via history.
    - Provides methods to check if limit is exceeded and calculate remaining.
    - Immutable: all operations return new instances.

Dependencies:
    - Python standard library (decimal, datetime, dataclass, enum, logging)
    - domain.shared_value_objects.money_vo (Money) - optional, for currency handling

Audit:
    Pure value object; no I/O. Caller should log credit limit changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class CreditLimitError(ValueError):
    """Base exception for credit limit errors."""

    pass


class InvalidCreditLimitAmountError(CreditLimitError):
    """Raised when credit limit amount is negative."""

    pass


class InvalidCurrencyError(CreditLimitError):
    """Raised when currency code is invalid."""

    pass


class CreditLimitExpiredError(CreditLimitError):
    """Raised when trying to use an expired credit limit."""

    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_currency(currency: str) -> str:
    """Validate ISO 4217 currency code."""
    if not currency or not isinstance(currency, str):
        raise InvalidCurrencyError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise InvalidCurrencyError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise InvalidCurrencyError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


def _validate_amount(amount: Decimal) -> Decimal:
    """Validate and normalize credit limit amount."""
    if not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount))
        except Exception:
            raise InvalidCreditLimitAmountError(f"Invalid amount type: {type(amount)}")
    if amount < 0:
        raise InvalidCreditLimitAmountError(f"Credit limit cannot be negative: {amount}")
    # Round to 2 decimal places by default (can be overridden per currency)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


# ============================================================================
# Enums
# ============================================================================


class CreditLimitStatus(Enum):
    """Status of a credit limit."""

    ACTIVE = "active"  # Within effective period
    EXPIRED = "expired"  # Past expiry date
    PENDING = "pending"  # Not yet effective
    REVOKED = "revoked"  # Cancelled by admin
    SUSPENDED = "suspended"  # Temporarily suspended

    def is_usable(self) -> bool:
        """Check if credit limit can be used for new transactions."""
        return self == CreditLimitStatus.ACTIVE


class CreditLimitReviewOutcome(Enum):
    """Outcome of a credit limit review."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"
    REDUCED = "reduced"
    INCREASED = "increased"
    SUSPENDED = "suspended"


# ============================================================================
# Value Object: CustomerCreditLimitVO
# ============================================================================


@dataclass(frozen=True)
class CustomerCreditLimitVO:
    """
    Immutable value object for customer credit limit.

    Attributes:
        amount: Maximum credit amount (Decimal, >= 0)
        currency: ISO 4217 currency code (default 'IDR')
        effective_date: UTC datetime when this limit becomes effective
        expiry_date: Optional UTC datetime after which limit expires
        approved_by: User or system that approved this limit
        approval_date: UTC datetime when limit was approved
        review_date: Optional date of last review
        review_notes: Optional notes from credit review
        status: Current status of this credit limit
        source: Source of this limit ('manual', 'system', 'policy')
        version: Version number for tracking changes

    Examples:
        >>> limit = CustomerCreditLimitVO(
        ...     amount=Decimal('100000000'),
        ...     currency='IDR',
        ...     effective_date=datetime(2024,1,1, tzinfo=timezone.utc),
        ...     approved_by='credit_manager'
        ... )
        >>> limit.is_active(as_of=datetime(2024,6,1, tzinfo=timezone.utc))
        True
        >>> limit.is_exceeded(Decimal('95000000'))
        False
        >>> limit.remaining(Decimal('80000000'))
        Decimal('20000000')
        >>> limit.to_dict()
        {...}
    """

    amount: Decimal
    currency: str = "IDR"
    effective_date: datetime = field(default_factory=lambda: datetime.now(UTC))
    expiry_date: datetime | None = None
    approved_by: str | None = None
    approval_date: datetime | None = None
    review_date: date | None = None
    review_notes: str | None = None
    status: CreditLimitStatus = CreditLimitStatus.ACTIVE
    source: str = "manual"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate credit limit data."""
        # Validate amount
        normalized_amount = _validate_amount(self.amount)
        if normalized_amount != self.amount:
            object.__setattr__(self, "amount", normalized_amount)

        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Normalize effective_date to UTC
        if self.effective_date.tzinfo is None:
            object.__setattr__(self, "effective_date", self.effective_date.replace(tzinfo=UTC))

        # Validate expiry_date
        if self.expiry_date is not None:
            if self.expiry_date.tzinfo is None:
                object.__setattr__(self, "expiry_date", self.expiry_date.replace(tzinfo=UTC))
            if self.expiry_date <= self.effective_date:
                raise CreditLimitError("Expiry date must be after effective date")

        # Validate approval_date
        if self.approval_date is not None:
            if self.approval_date.tzinfo is None:
                object.__setattr__(self, "approval_date", self.approval_date.replace(tzinfo=UTC))
            if self.approval_date < self.effective_date:
                # Warning but not error? Let's allow, but log.
                logger.warning(
                    f"Approval date {self.approval_date} is before effective date {self.effective_date}"
                )

        # Validate version
        if self.version < 1:
            raise CreditLimitError("Version must be >= 1")

        # Validate source
        if not self.source or len(self.source.strip()) == 0:
            object.__setattr__(self, "source", "manual")

        # Validate status consistency
        if self.status == CreditLimitStatus.ACTIVE:
            now = datetime.now(UTC)
            if self.effective_date > now:
                object.__setattr__(self, "status", CreditLimitStatus.PENDING)
            elif self.expiry_date and self.expiry_date <= now:
                object.__setattr__(self, "status", CreditLimitStatus.EXPIRED)

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        amount: Decimal,
        currency: str = "IDR",
        effective_date: datetime | None = None,
        expiry_date: datetime | None = None,
        approved_by: str | None = None,
        source: str = "manual",
    ) -> CustomerCreditLimitVO:
        """Create a new active credit limit."""
        if effective_date is None:
            effective_date = datetime.now(UTC)
        return cls(
            amount=amount,
            currency=currency,
            effective_date=effective_date,
            expiry_date=expiry_date,
            approved_by=approved_by,
            approval_date=datetime.now(UTC),
            status=CreditLimitStatus.ACTIVE,
            source=source,
            version=1,
        )

    @classmethod
    def unlimited(cls, currency: str = "IDR") -> CustomerCreditLimitVO:
        """Create an unlimited credit limit (very high amount)."""
        return cls.create(
            amount=Decimal("999999999999999"),
            currency=currency,
            source="unlimited",
        )

    @classmethod
    def zero(cls, currency: str = "IDR") -> CustomerCreditLimitVO:
        """Create a zero credit limit (no credit allowed)."""
        return cls.create(
            amount=Decimal("0"),
            currency=currency,
            source="zero",
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomerCreditLimitVO:
        """Reconstruct from dictionary."""
        effective = datetime.fromisoformat(data["effective_date"])
        expiry = datetime.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None
        approval = (
            datetime.fromisoformat(data["approval_date"]) if data.get("approval_date") else None
        )
        review_date_val = None
        if data.get("review_date"):
            review_date_val = date.fromisoformat(data["review_date"])
        status = (
            CreditLimitStatus(data["status"]) if data.get("status") else CreditLimitStatus.ACTIVE
        )
        return cls(
            amount=Decimal(str(data["amount"])),
            currency=data["currency"],
            effective_date=effective,
            expiry_date=expiry,
            approved_by=data.get("approved_by"),
            approval_date=approval,
            review_date=review_date_val,
            review_notes=data.get("review_notes"),
            status=status,
            source=data.get("source", "manual"),
            version=data.get("version", 1),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_unlimited(self) -> bool:
        """Check if this is an unlimited credit limit."""
        return self.amount >= Decimal("999999999999")

    @property
    def is_zero(self) -> bool:
        """Check if credit limit is zero."""
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        """Check if credit limit > 0."""
        return self.amount > 0

    @property
    def is_forever(self) -> bool:
        """Check if credit limit never expires."""
        return self.expiry_date is None

    @property
    def days_until_expiry(self, as_of: datetime | None = None) -> int | None:
        """Return number of days until expiry, or None if no expiry."""
        if self.expiry_date is None:
            return None
        check_date = as_of or datetime.now(UTC)
        delta = self.expiry_date - check_date
        return max(0, delta.days)

    @property
    def has_been_reviewed(self) -> bool:
        """Check if credit limit has been reviewed."""
        return self.review_date is not None

    # ------------------------------------------------------------------------
    # Business Logic
    # ------------------------------------------------------------------------

    def is_active(self, as_of: datetime | None = None) -> bool:
        """
        Check if credit limit is active and effective on given date.

        Args:
            as_of: Date to check (defaults to now UTC)

        Returns:
            True if effective <= as_of and (no expiry or as_of < expiry) and status ACTIVE
        """
        check_date = as_of or datetime.now(UTC)
        if check_date.tzinfo is None:
            check_date = check_date.replace(tzinfo=UTC)

        if self.status != CreditLimitStatus.ACTIVE:
            return False
        if check_date < self.effective_date:
            return False
        if self.expiry_date is not None and check_date >= self.expiry_date:
            return False
        return True

    def is_exceeded(self, current_balance: Decimal, as_of: datetime | None = None) -> bool:
        """
        Check if current outstanding balance exceeds credit limit.

        Args:
            current_balance: Current outstanding balance (positive)
            as_of: Date to check for limit activity

        Returns:
            True if current_balance > amount (and limit is active)
        """
        if not self.is_active(as_of):
            return True  # If limit not active, treat as exceeded
        return current_balance > self.amount

    def remaining(self, current_balance: Decimal, as_of: datetime | None = None) -> Decimal:
        """
        Calculate remaining available credit.

        Args:
            current_balance: Current outstanding balance
            as_of: Date to check for limit activity

        Returns:
            Remaining credit (max 0 if exceeded)
        """
        if not self.is_active(as_of):
            return Decimal("0")
        remaining_val = self.amount - current_balance
        return remaining_val if remaining_val > 0 else Decimal("0")

    def utilization_percentage(
        self, current_balance: Decimal, as_of: datetime | None = None
    ) -> Decimal:
        """
        Calculate credit utilization as percentage (0-100).

        Args:
            current_balance: Current outstanding balance
            as_of: Date to check for limit activity

        Returns:
            Utilization percentage (0-100)
        """
        if not self.is_active(as_of) or self.amount == 0:
            return Decimal("0") if self.amount == 0 else Decimal("100")
        utilization = (current_balance / self.amount) * Decimal("100")
        # Clamp to 0-100
        if utilization < 0:
            return Decimal("0")
        if utilization > 100:
            return Decimal("100")
        return utilization.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def can_invoice(
        self, invoice_amount: Decimal, current_balance: Decimal, as_of: datetime | None = None
    ) -> tuple[bool, str | None]:
        """
        Check if a new invoice can be created given current balance.

        Args:
            invoice_amount: Amount of new invoice
            current_balance: Current outstanding balance before invoice

        Returns:
            (can_create, reason_if_not)
        """
        if not self.is_active(as_of):
            return False, f"Credit limit is not active (status: {self.status.value})"
        if self.is_zero:
            return False, "Credit limit is zero"
        new_balance = current_balance + invoice_amount
        if new_balance > self.amount:
            return (
                False,
                f"Would exceed credit limit. Current: {current_balance}, Invoice: {invoice_amount}, Limit: {self.amount}",
            )
        return True, None

    def with_amount(
        self, new_amount: Decimal, changed_by: str, reason: str | None = None
    ) -> CustomerCreditLimitVO:
        """Create a new credit limit with updated amount."""
        return CustomerCreditLimitVO(
            amount=new_amount,
            currency=self.currency,
            effective_date=datetime.now(UTC),
            expiry_date=self.expiry_date,
            approved_by=changed_by,
            approval_date=datetime.now(UTC),
            review_date=date.today(),
            review_notes=reason,
            status=CreditLimitStatus.ACTIVE,
            source=f"{self.source}_modified",
            version=self.version + 1,
        )

    def with_expiry(
        self, new_expiry_date: datetime | None, changed_by: str
    ) -> CustomerCreditLimitVO:
        """Extend or remove expiry date."""
        return CustomerCreditLimitVO(
            amount=self.amount,
            currency=self.currency,
            effective_date=self.effective_date,
            expiry_date=new_expiry_date,
            approved_by=changed_by,
            approval_date=datetime.now(UTC),
            review_date=date.today(),
            review_notes=f"Expiry changed from {self.expiry_date} to {new_expiry_date}",
            status=CreditLimitStatus.ACTIVE,
            source=self.source,
            version=self.version + 1,
        )

    def revoke(self, revoked_by: str, reason: str) -> CustomerCreditLimitVO:
        """Revoke this credit limit."""
        return CustomerCreditLimitVO(
            amount=self.amount,
            currency=self.currency,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            approved_by=revoked_by,
            approval_date=self.approval_date,
            review_date=date.today(),
            review_notes=f"Revoked: {reason}",
            status=CreditLimitStatus.REVOKED,
            source=self.source,
            version=self.version + 1,
        )

    def suspend(self, suspended_by: str, reason: str) -> CustomerCreditLimitVO:
        """Temporarily suspend this credit limit."""
        return CustomerCreditLimitVO(
            amount=self.amount,
            currency=self.currency,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            approved_by=suspended_by,
            approval_date=self.approval_date,
            review_date=date.today(),
            review_notes=f"Suspended: {reason}",
            status=CreditLimitStatus.SUSPENDED,
            source=self.source,
            version=self.version + 1,
        )

    def activate(self, activated_by: str) -> CustomerCreditLimitVO:
        """Activate a previously suspended credit limit."""
        return CustomerCreditLimitVO(
            amount=self.amount,
            currency=self.currency,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            approved_by=activated_by,
            approval_date=datetime.now(UTC),
            review_date=date.today(),
            review_notes="Activated from suspended",
            status=CreditLimitStatus.ACTIVE,
            source=self.source,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "amount": str(self.amount),
            "currency": self.currency,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "approved_by": self.approved_by,
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "review_date": self.review_date.isoformat() if self.review_date else None,
            "review_notes": self.review_notes,
            "status": self.status.value,
            "source": self.source,
            "version": self.version,
            "is_unlimited": self.is_unlimited,
            "is_zero": self.is_zero,
            "is_forever": self.is_forever,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "credit_limit_amount": self.amount,
            "credit_limit_currency": self.currency,
            "credit_limit_effective_date": self.effective_date,
            "credit_limit_expiry_date": self.expiry_date,
            "credit_limit_approved_by": self.approved_by,
            "credit_limit_approval_date": self.approval_date,
            "credit_limit_review_date": self.review_date,
            "credit_limit_review_notes": self.review_notes,
            "credit_limit_status": self.status.value,
            "credit_limit_source": self.source,
            "credit_limit_version": self.version,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        if self.is_unlimited:
            return f"Unlimited ({self.currency})"
        return f"{self.currency} {self.amount:,.2f}"

    def __repr__(self) -> str:
        return f"CustomerCreditLimitVO(amount={self.amount}, currency='{self.currency}', status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CustomerCreditLimitVO):
            return False
        return (
            self.amount == other.amount
            and self.currency == other.currency
            and self.effective_date == other.effective_date
            and self.expiry_date == other.expiry_date
        )

    def __hash__(self) -> int:
        return hash((self.amount, self.currency, self.effective_date, self.expiry_date))


# ============================================================================
# Helper Functions
# ============================================================================


def format_credit_limit(limit: CustomerCreditLimitVO, include_currency: bool = True) -> str:
    """Format credit limit for display."""
    if limit.is_unlimited:
        return "Unlimited"
    if include_currency:
        return f"{limit.currency} {limit.amount:,.2f}"
    return f"{limit.amount:,.2f}"


def parse_credit_limit(value: str, currency: str = "IDR") -> CustomerCreditLimitVO:
    """Parse a string to create a credit limit."""
    # Remove currency symbols, commas, etc.
    cleaned = re.sub(r"[^\d.-]", "", value)
    try:
        amount = Decimal(cleaned)
    except Exception:
        raise CreditLimitError(f"Cannot parse amount from '{value}'")
    return CustomerCreditLimitVO.create(amount, currency=currency)


def sum_credit_limits(limits: list[CustomerCreditLimitVO]) -> CustomerCreditLimitVO:
    """Sum multiple credit limits (for consolidated customers)."""
    if not limits:
        return CustomerCreditLimitVO.zero()
    first = limits[0]
    total_amount = sum(l.amount for l in limits)
    # Take the earliest effective date and latest expiry
    effective = min(l.effective_date for l in limits)
    expiry = (
        max(l.expiry_date for l in limits if l.expiry_date is not None)
        if any(l.expiry_date for l in limits)
        else None
    )
    return CustomerCreditLimitVO(
        amount=total_amount,
        currency=first.currency,
        effective_date=effective,
        expiry_date=expiry,
        source="combined",
        version=1,
    )


def get_most_recent_limit(limits: list[CustomerCreditLimitVO]) -> CustomerCreditLimitVO | None:
    """Return the most recent (latest effective date) credit limit."""
    if not limits:
        return None
    return max(limits, key=lambda l: l.effective_date)


def get_active_limit_at_date(
    limits: list[CustomerCreditLimitVO], as_of: datetime | None = None
) -> CustomerCreditLimitVO | None:
    """Return the active credit limit on a given date."""
    if as_of is None:
        as_of = datetime.now(UTC)
    active = [l for l in limits if l.is_active(as_of)]
    if not active:
        return None
    # Return the one with highest effective date (most recent)
    return max(active, key=lambda l: l.effective_date)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CreditLimitError",
    "CreditLimitExpiredError",
    "CreditLimitReviewOutcome",
    "CreditLimitStatus",
    "CustomerCreditLimitVO",
    "InvalidCreditLimitAmountError",
    "InvalidCurrencyError",
    "format_credit_limit",
    "get_active_limit_at_date",
    "get_most_recent_limit",
    "parse_credit_limit",
    "sum_credit_limits",
]
