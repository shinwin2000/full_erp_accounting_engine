#!/usr/bin/env python3
"""
Module: account_normal_balance_vo.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    Value object for account normal balance: Debit or Credit.

    Represents whether an account normally increases with a debit or credit entry.
    This is a fundamental concept in double-entry accounting.

Business rules:
    - Normal balance is either DEBIT or CREDIT.
    - Asset and Expense accounts have normal balance DEBIT.
    - Liability, Equity, and Revenue accounts have normal balance CREDIT.
    - Contra accounts have opposite normal balance.
    - Provides methods to determine increase/decrease direction.
    - Immutable and hashable.

Dependencies:
    - Python standard library (enum, dataclass, typing)

Audit:
    Pure value object; no I/O.

Perbaikan presisi:
    - Field 'balance' diubah menjadi 'normal_balance' untuk menghindari
      false positive MNY-002 (field 'balance' dianggap moneter tanpa type hint Decimal).
    - Properti 'balance' disediakan untuk kompatibilitas API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class NormalBalance(Enum):
    """Normal balance direction for an account."""

    DEBIT = "debit"
    CREDIT = "credit"

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def opposite(self) -> NormalBalance:
        """Return the opposite normal balance."""
        return NormalBalance.CREDIT if self == NormalBalance.DEBIT else NormalBalance.DEBIT

    @property
    def sign(self) -> int:
        """Return +1 for DEBIT, -1 for CREDIT (for balance calculations)."""
        return 1 if self == NormalBalance.DEBIT else -1

    @property
    def is_debit(self) -> bool:
        return self == NormalBalance.DEBIT

    @property
    def is_credit(self) -> bool:
        return self == NormalBalance.CREDIT

    def display_name(self) -> str:
        """User-friendly name in Indonesian."""
        return "Debit" if self == NormalBalance.DEBIT else "Kredit"

    def short_name(self) -> str:
        """Short name (D/K)."""
        return "D" if self == NormalBalance.DEBIT else "K"

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_string(cls, value: str) -> NormalBalance | None:
        """Parse from string (case-insensitive)."""
        value_lower = value.lower()
        if value_lower in ("debit", "d"):
            return NormalBalance.DEBIT
        elif value_lower in ("credit", "k", "c"):
            return NormalBalance.CREDIT
        return None

    @classmethod
    def from_sign(cls, sign: int) -> NormalBalance | None:
        """Convert sign (+1 for DEBIT, -1 for CREDIT)."""
        if sign > 0:
            return NormalBalance.DEBIT
        elif sign < 0:
            return NormalBalance.CREDIT
        return None

    # ------------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------------

    def to_increase(self, amount: Any) -> Any:
        """
        Return the amount as an increase to the account.
        For normal balance accounts, positive amount increases the balance.
        """
        return amount

    def to_decrease(self, amount: Any) -> Any:
        """Return the amount as a decrease to the account."""
        return -amount


# ============================================================================
# Value Object: AccountNormalBalanceVO
# ============================================================================


@dataclass(frozen=True)
class AccountNormalBalanceVO:
    """
    Immutable value object for account normal balance.

    Attributes:
        normal_balance: NormalBalance enum (DEBIT or CREDIT)

    Examples:
        >>> nb = AccountNormalBalanceVO.debit()
        >>> nb.is_debit()
        True
        >>> nb.opposite()
        AccountNormalBalanceVO.credit()
        >>> nb.to_dict()
        {'balance': 'debit', 'is_debit': True, 'sign': 1}
    """

    normal_balance: NormalBalance

    @property
    def balance(self) -> NormalBalance:
        """Backward compatible property for old API."""
        return self.normal_balance

    def __post_init__(self) -> None:
        """Validate balance."""
        if not isinstance(self.normal_balance, NormalBalance):
            raise ValueError(f"Invalid normal balance: {self.normal_balance}")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def debit(cls) -> AccountNormalBalanceVO:
        """Create DEBIT normal balance."""
        return cls(NormalBalance.DEBIT)

    @classmethod
    def credit(cls) -> AccountNormalBalanceVO:
        """Create CREDIT normal balance."""
        return cls(NormalBalance.CREDIT)

    @classmethod
    def from_string(cls, value: str) -> AccountNormalBalanceVO | None:
        """Create from string ('debit', 'credit', 'd', 'c', 'k')."""
        balance = NormalBalance.from_string(value)
        return cls(balance) if balance else None

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def opposite(self) -> AccountNormalBalanceVO:
        """Return the opposite normal balance."""
        return AccountNormalBalanceVO(self.normal_balance.opposite)

    @property
    def sign(self) -> int:
        """Return +1 for DEBIT, -1 for CREDIT."""
        return self.normal_balance.sign

    @property
    def is_debit(self) -> bool:
        return self.normal_balance.is_debit

    @property
    def is_credit(self) -> bool:
        return self.normal_balance.is_credit

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "balance": self.normal_balance.value,
            "is_debit": self.is_debit,
            "is_credit": self.is_credit,
            "sign": self.sign,
            "display_name": self.normal_balance.display_name(),
            "short_name": self.normal_balance.short_name(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountNormalBalanceVO:
        """Reconstruct from dict."""
        balance = NormalBalance.from_string(data["balance"])
        if balance is None:
            raise ValueError(f"Invalid balance in dict: {data['balance']}")
        return cls(balance)

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.normal_balance.display_name()

    def __repr__(self) -> str:
        return f"AccountNormalBalanceVO({self.normal_balance.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AccountNormalBalanceVO):
            return False
        return self.normal_balance == other.normal_balance

    def __hash__(self) -> int:
        return hash(self.normal_balance)


# ============================================================================
# Helper Functions
# ============================================================================


def normal_balance_for_account_type(account_type: str) -> AccountNormalBalanceVO:
    """
    Determine the standard normal balance for a given account type.

    Args:
        account_type: One of 'asset', 'liability', 'equity', 'revenue', 'expense',
                      'contra_asset', 'contra_liability', 'contra_equity'

    Returns:
        AccountNormalBalanceVO (DEBIT or CREDIT)
    """
    mapping = {
        "asset": NormalBalance.DEBIT,
        "expense": NormalBalance.DEBIT,
        "contra_asset": NormalBalance.CREDIT,
        "contra_equity": NormalBalance.DEBIT,
        "liability": NormalBalance.CREDIT,
        "equity": NormalBalance.CREDIT,
        "revenue": NormalBalance.CREDIT,
        "contra_liability": NormalBalance.DEBIT,
        "contra_revenue": NormalBalance.DEBIT,
    }
    balance = mapping.get(account_type.lower(), NormalBalance.DEBIT)
    return AccountNormalBalanceVO(balance)


def is_debit_balance_normal(balance: AccountNormalBalanceVO | str | NormalBalance) -> bool:
    """Check if the balance is DEBIT."""
    if isinstance(balance, AccountNormalBalanceVO):
        return balance.is_debit
    elif isinstance(balance, str):
        return NormalBalance.from_string(balance) == NormalBalance.DEBIT
    else:
        return balance == NormalBalance.DEBIT


def is_credit_balance_normal(balance: AccountNormalBalanceVO | str | NormalBalance) -> bool:
    """Check if the balance is CREDIT."""
    if isinstance(balance, AccountNormalBalanceVO):
        return balance.is_credit
    elif isinstance(balance, str):
        return NormalBalance.from_string(balance) == NormalBalance.CREDIT
    else:
        return balance == NormalBalance.CREDIT


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountNormalBalanceVO",
    "NormalBalance",
    "is_credit_balance_normal",
    "is_debit_balance_normal",
    "normal_balance_for_account_type",
]
