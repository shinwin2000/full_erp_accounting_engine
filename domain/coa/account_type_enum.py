#!/usr/bin/env python3
"""
Module: account_type_enum.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    Enum for account types: Asset, Liability, Equity, Revenue, Expense,
    and contra accounts.

    Defines standard account types in double-entry accounting, which determine
    the normal balance and financial statement presentation.

Business rules:
    - Asset and Expense accounts have normal balance DEBIT.
    - Liability, Equity, and Revenue accounts have normal balance CREDIT.
    - Contra accounts reverse the normal balance of their base type.
    - Provides mapping to financial statements (Balance Sheet / Income Statement).
    - Supports classification for reporting and validation.

Dependencies:
    - Python standard library (enum, typing)

Audit:
    Pure enum; no I/O.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

# ============================================================================
# Account Type Enum
# ============================================================================


class AccountType(Enum):
    """
    Standard account types in double-entry accounting.

    Attributes:
        ASSET: Resources owned (normal balance DEBIT)
        LIABILITY: Obligations owed (normal balance CREDIT)
        EQUITY: Owner's residual interest (normal balance CREDIT)
        REVENUE: Income from operations (normal balance CREDIT)
        EXPENSE: Costs incurred (normal balance DEBIT)
        CONTRA_ASSET: Reduces asset value (normal balance CREDIT)
        CONTRA_LIABILITY: Reduces liability value (normal balance DEBIT)
        CONTRA_EQUITY: Reduces equity value (normal balance DEBIT)
        CONTRA_REVENUE: Reduces revenue (normal balance DEBIT)
        CONTRA_EXPENSE: Reduces expense (normal balance CREDIT)
    """

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"
    CONTRA_ASSET = "contra_asset"
    CONTRA_LIABILITY = "contra_liability"
    CONTRA_EQUITY = "contra_equity"
    CONTRA_REVENUE = "contra_revenue"
    CONTRA_EXPENSE = "contra_expense"

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def normal_balance(self) -> str:
        """Return the normal balance ('debit' or 'credit')."""
        mapping = {
            AccountType.ASSET: "debit",
            AccountType.EXPENSE: "debit",
            AccountType.CONTRA_EQUITY: "debit",
            AccountType.CONTRA_LIABILITY: "debit",
            AccountType.CONTRA_REVENUE: "debit",
            AccountType.LIABILITY: "credit",
            AccountType.EQUITY: "credit",
            AccountType.REVENUE: "credit",
            AccountType.CONTRA_ASSET: "credit",
            AccountType.CONTRA_EXPENSE: "credit",
        }
        return mapping.get(self, "debit")

    @property
    def normal_balance_enum(self) -> NormalBalance:
        """Return NormalBalance enum."""
        from domain.coa.account_normal_balance_vo import NormalBalance

        return NormalBalance.DEBIT if self.normal_balance == "debit" else NormalBalance.CREDIT

    @property
    def financial_statement(self) -> str:
        """
        Return which financial statement this account appears on.
        'balance_sheet' or 'income_statement'.
        """
        balance_sheet_types = {
            AccountType.ASSET,
            AccountType.LIABILITY,
            AccountType.EQUITY,
            AccountType.CONTRA_ASSET,
            AccountType.CONTRA_LIABILITY,
            AccountType.CONTRA_EQUITY,
        }
        return "balance_sheet" if self in balance_sheet_types else "income_statement"

    @property
    def is_balance_sheet(self) -> bool:
        return self.financial_statement == "balance_sheet"

    @property
    def is_income_statement(self) -> bool:
        return self.financial_statement == "income_statement"

    @property
    def is_contra(self) -> bool:
        """Return True if this is a contra account type."""
        contra_types = {
            AccountType.CONTRA_ASSET,
            AccountType.CONTRA_LIABILITY,
            AccountType.CONTRA_EQUITY,
            AccountType.CONTRA_REVENUE,
            AccountType.CONTRA_EXPENSE,
        }
        return self in contra_types

    @property
    def base_type(self) -> AccountType | None:
        """Return the base account type that this contra account offsets."""
        base_mapping = {
            AccountType.CONTRA_ASSET: AccountType.ASSET,
            AccountType.CONTRA_LIABILITY: AccountType.LIABILITY,
            AccountType.CONTRA_EQUITY: AccountType.EQUITY,
            AccountType.CONTRA_REVENUE: AccountType.REVENUE,
            AccountType.CONTRA_EXPENSE: AccountType.EXPENSE,
        }
        return base_mapping.get(self)

    @property
    def display_name(self) -> str:
        """User-friendly name in Indonesian."""
        names = {
            AccountType.ASSET: "Aset",
            AccountType.LIABILITY: "Kewajiban",
            AccountType.EQUITY: "Ekuitas",
            AccountType.REVENUE: "Pendapatan",
            AccountType.EXPENSE: "Beban",
            AccountType.CONTRA_ASSET: "Kontra Aset",
            AccountType.CONTRA_LIABILITY: "Kontra Kewajiban",
            AccountType.CONTRA_EQUITY: "Kontra Ekuitas",
            AccountType.CONTRA_REVENUE: "Kontra Pendapatan",
            AccountType.CONTRA_EXPENSE: "Kontra Beban",
        }
        return names.get(self, self.value)

    @property
    def hierarchy_level(self) -> int:
        """Return hierarchy level for reporting (1-3)."""
        levels = {
            AccountType.ASSET: 1,
            AccountType.LIABILITY: 1,
            AccountType.EQUITY: 1,
            AccountType.REVENUE: 1,
            AccountType.EXPENSE: 1,
            AccountType.CONTRA_ASSET: 2,
            AccountType.CONTRA_LIABILITY: 2,
            AccountType.CONTRA_EQUITY: 2,
            AccountType.CONTRA_REVENUE: 2,
            AccountType.CONTRA_EXPENSE: 2,
        }
        return levels.get(self, 1)

    # ------------------------------------------------------------------------
    # Classification methods
    # ------------------------------------------------------------------------

    def is_asset_like(self) -> bool:
        """Return True for ASSET and CONTRA_LIABILITY and CONTRA_EQUITY."""
        return self in (AccountType.ASSET, AccountType.CONTRA_LIABILITY, AccountType.CONTRA_EQUITY)

    def is_liability_like(self) -> bool:
        """Return True for LIABILITY and CONTRA_ASSET."""
        return self in (AccountType.LIABILITY, AccountType.CONTRA_ASSET)

    def is_equity_like(self) -> bool:
        """Return True for EQUITY and CONTRA_EQUITY (but CONTRA_EQUITY already included)."""
        return self == AccountType.EQUITY

    def is_revenue_like(self) -> bool:
        """Return True for REVENUE and CONTRA_EXPENSE."""
        return self in (AccountType.REVENUE, AccountType.CONTRA_EXPENSE)

    def is_expense_like(self) -> bool:
        """Return True for EXPENSE and CONTRA_REVENUE."""
        return self in (AccountType.EXPENSE, AccountType.CONTRA_REVENUE)

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_string(cls, value: str) -> AccountType | None:
        """Parse from string (case-insensitive)."""
        value_lower = value.lower()
        for member in cls:
            if member.value == value_lower or member.name.lower() == value_lower:
                return member
        return None

    @classmethod
    def get_balance_sheet_types(cls) -> list[AccountType]:
        """Return all balance sheet account types."""
        return [t for t in cls if t.is_balance_sheet]

    @classmethod
    def get_income_statement_types(cls) -> list[AccountType]:
        """Return all income statement account types."""
        return [t for t in cls if t.is_income_statement]

    @classmethod
    def get_contra_types(cls) -> list[AccountType]:
        """Return all contra account types."""
        return [t for t in cls if t.is_contra]

    @classmethod
    def get_non_contra_types(cls) -> list[AccountType]:
        """Return all non-contra account types."""
        return [t for t in cls if not t.is_contra]

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "name": self.name,
            "value": self.value,
            "normal_balance": self.normal_balance,
            "financial_statement": self.financial_statement,
            "is_contra": self.is_contra,
            "display_name": self.display_name,
            "hierarchy_level": self.hierarchy_level,
        }


# ============================================================================
# Helper Functions
# ============================================================================


def is_valid_account_type(type_str: str) -> bool:
    """Check if string is a valid account type."""
    return AccountType.from_string(type_str) is not None


def get_account_type_display(type_str: AccountType | str) -> str:
    """Get display name for account type."""
    if isinstance(type_str, str):
        acc_type = AccountType.from_string(type_str)
        if acc_type is None:
            return type_str
        return acc_type.display_name
    return type_str.display_name


def get_normal_balance_from_type(account_type: AccountType | str) -> str:
    """Get normal balance string from account type."""
    if isinstance(account_type, str):
        acc_type = AccountType.from_string(account_type)
        if acc_type is None:
            return "debit"
        return acc_type.normal_balance
    return account_type.normal_balance


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountType",
    "get_account_type_display",
    "get_normal_balance_from_type",
    "is_valid_account_type",
]
