"""
Tests for domain/coa/account_type_enum.py

Covers:
- AccountType properties: normal_balance, normal_balance_enum, financial_statement,
  is_balance_sheet/is_income_statement, is_contra, base_type, display_name,
  hierarchy_level
- Classification methods: is_asset_like/is_liability_like/is_equity_like/
  is_revenue_like/is_expense_like
- Factory/class methods: from_string, get_balance_sheet_types,
  get_income_statement_types, get_contra_types, get_non_contra_types
- to_dict()
- Module helpers: is_valid_account_type, get_account_type_display,
  get_normal_balance_from_type
"""

from __future__ import annotations

import pytest

from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.account_type_enum import (
    AccountType,
    get_account_type_display,
    get_normal_balance_from_type,
    is_valid_account_type,
)

# ============================================================================
# normal_balance / normal_balance_enum
# ============================================================================


class TestNormalBalance:
    @pytest.mark.parametrize(
        "account_type, expected",
        [
            (AccountType.ASSET, "debit"),
            (AccountType.EXPENSE, "debit"),
            (AccountType.CONTRA_EQUITY, "debit"),
            (AccountType.CONTRA_LIABILITY, "debit"),
            (AccountType.CONTRA_REVENUE, "debit"),
            (AccountType.LIABILITY, "credit"),
            (AccountType.EQUITY, "credit"),
            (AccountType.REVENUE, "credit"),
            (AccountType.CONTRA_ASSET, "credit"),
            (AccountType.CONTRA_EXPENSE, "credit"),
        ],
    )
    def test_normal_balance_mapping(self, account_type, expected):
        assert account_type.normal_balance == expected

    def test_normal_balance_enum_debit(self):
        assert AccountType.ASSET.normal_balance_enum == NormalBalance.DEBIT

    def test_normal_balance_enum_credit(self):
        assert AccountType.LIABILITY.normal_balance_enum == NormalBalance.CREDIT


# ============================================================================
# financial_statement / is_balance_sheet / is_income_statement
# ============================================================================


class TestFinancialStatement:
    @pytest.mark.parametrize(
        "account_type",
        [
            AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY,
            AccountType.CONTRA_ASSET, AccountType.CONTRA_LIABILITY, AccountType.CONTRA_EQUITY,
        ],
    )
    def test_balance_sheet_types(self, account_type):
        assert account_type.financial_statement == "balance_sheet"
        assert account_type.is_balance_sheet is True
        assert account_type.is_income_statement is False

    @pytest.mark.parametrize(
        "account_type",
        [AccountType.REVENUE, AccountType.EXPENSE, AccountType.CONTRA_REVENUE, AccountType.CONTRA_EXPENSE],
    )
    def test_income_statement_types(self, account_type):
        assert account_type.financial_statement == "income_statement"
        assert account_type.is_income_statement is True
        assert account_type.is_balance_sheet is False


# ============================================================================
# is_contra / base_type
# ============================================================================


class TestContra:
    @pytest.mark.parametrize(
        "account_type",
        [
            AccountType.CONTRA_ASSET, AccountType.CONTRA_LIABILITY,
            AccountType.CONTRA_EQUITY, AccountType.CONTRA_REVENUE, AccountType.CONTRA_EXPENSE,
        ],
    )
    def test_is_contra_true(self, account_type):
        assert account_type.is_contra is True

    @pytest.mark.parametrize(
        "account_type",
        [AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE, AccountType.EXPENSE],
    )
    def test_is_contra_false(self, account_type):
        assert account_type.is_contra is False

    def test_base_type_of_contra_asset(self):
        assert AccountType.CONTRA_ASSET.base_type == AccountType.ASSET

    def test_base_type_of_contra_expense(self):
        assert AccountType.CONTRA_EXPENSE.base_type == AccountType.EXPENSE

    def test_base_type_of_non_contra_is_none(self):
        assert AccountType.ASSET.base_type is None


# ============================================================================
# display_name / hierarchy_level
# ============================================================================


class TestDisplayAndHierarchy:
    def test_display_name_known(self):
        assert AccountType.ASSET.display_name == "Aset"
        assert AccountType.EXPENSE.display_name == "Beban"

    def test_hierarchy_level_base_types_are_1(self):
        assert AccountType.ASSET.hierarchy_level == 1
        assert AccountType.REVENUE.hierarchy_level == 1

    def test_hierarchy_level_contra_types_are_2(self):
        assert AccountType.CONTRA_ASSET.hierarchy_level == 2
        assert AccountType.CONTRA_EXPENSE.hierarchy_level == 2


# ============================================================================
# Classification methods
# ============================================================================


class TestClassificationMethods:
    def test_is_asset_like(self):
        assert AccountType.ASSET.is_asset_like() is True
        assert AccountType.CONTRA_LIABILITY.is_asset_like() is True
        assert AccountType.CONTRA_EQUITY.is_asset_like() is True
        assert AccountType.LIABILITY.is_asset_like() is False

    def test_is_liability_like(self):
        assert AccountType.LIABILITY.is_liability_like() is True
        assert AccountType.CONTRA_ASSET.is_liability_like() is True
        assert AccountType.ASSET.is_liability_like() is False

    def test_is_equity_like_only_true_for_equity_itself(self):
        assert AccountType.EQUITY.is_equity_like() is True
        # Despite the docstring mentioning CONTRA_EQUITY, the implementation
        # only matches AccountType.EQUITY exactly.
        assert AccountType.CONTRA_EQUITY.is_equity_like() is False

    def test_is_revenue_like(self):
        assert AccountType.REVENUE.is_revenue_like() is True
        assert AccountType.CONTRA_EXPENSE.is_revenue_like() is True
        assert AccountType.EXPENSE.is_revenue_like() is False

    def test_is_expense_like(self):
        assert AccountType.EXPENSE.is_expense_like() is True
        assert AccountType.CONTRA_REVENUE.is_expense_like() is True
        assert AccountType.REVENUE.is_expense_like() is False


# ============================================================================
# from_string / get_*_types class methods
# ============================================================================


class TestFromStringAndCollections:
    def test_from_string_by_value(self):
        assert AccountType.from_string("asset") == AccountType.ASSET

    def test_from_string_by_name(self):
        assert AccountType.from_string("ASSET") == AccountType.ASSET

    def test_from_string_case_insensitive_value(self):
        assert AccountType.from_string("Contra_Asset") == AccountType.CONTRA_ASSET

    def test_from_string_unknown_returns_none(self):
        assert AccountType.from_string("nonexistent") is None

    def test_get_balance_sheet_types(self):
        types = AccountType.get_balance_sheet_types()
        assert AccountType.ASSET in types
        assert AccountType.REVENUE not in types

    def test_get_income_statement_types(self):
        types = AccountType.get_income_statement_types()
        assert AccountType.REVENUE in types
        assert AccountType.ASSET not in types

    def test_get_contra_types(self):
        types = AccountType.get_contra_types()
        assert AccountType.CONTRA_ASSET in types
        assert AccountType.ASSET not in types
        assert len(types) == 5

    def test_get_non_contra_types(self):
        types = AccountType.get_non_contra_types()
        assert AccountType.ASSET in types
        assert AccountType.CONTRA_ASSET not in types
        assert len(types) == 5


# ============================================================================
# to_dict
# ============================================================================


class TestToDict:
    def test_to_dict_contains_expected_fields(self):
        d = AccountType.ASSET.to_dict()
        assert d == {
            "name": "ASSET",
            "value": "asset",
            "normal_balance": "debit",
            "financial_statement": "balance_sheet",
            "is_contra": False,
            "display_name": "Aset",
            "hierarchy_level": 1,
        }


# ============================================================================
# Module-level helper functions
# ============================================================================


class TestModuleHelpers:
    def test_is_valid_account_type_true(self):
        assert is_valid_account_type("asset") is True

    def test_is_valid_account_type_false(self):
        assert is_valid_account_type("not_a_type") is False

    def test_get_account_type_display_from_string(self):
        assert get_account_type_display("asset") == "Aset"

    def test_get_account_type_display_from_invalid_string_returns_input(self):
        assert get_account_type_display("bogus") == "bogus"

    def test_get_account_type_display_from_enum(self):
        assert get_account_type_display(AccountType.LIABILITY) == "Kewajiban"

    def test_get_normal_balance_from_type_string(self):
        assert get_normal_balance_from_type("liability") == "credit"

    def test_get_normal_balance_from_type_invalid_string_defaults_debit(self):
        assert get_normal_balance_from_type("bogus") == "debit"

    def test_get_normal_balance_from_type_enum(self):
        assert get_normal_balance_from_type(AccountType.EQUITY) == "credit"
