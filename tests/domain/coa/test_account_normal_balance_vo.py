"""
Tests for domain/coa/account_normal_balance_vo.py

Covers:
- NormalBalance enum: opposite, sign, is_debit/is_credit, display_name,
  short_name, from_string, from_sign, to_increase/to_decrease
- AccountNormalBalanceVO: construction/validation, factories (debit/credit/
  from_string), opposite/sign/is_debit/is_credit, to_dict/from_dict,
  __str__/__repr__/__eq__/__hash__
- Module helpers: normal_balance_for_account_type, is_debit_balance_normal,
  is_credit_balance_normal
"""

from __future__ import annotations

import pytest

from domain.coa.account_normal_balance_vo import (
    AccountNormalBalanceVO,
    NormalBalance,
    is_credit_balance_normal,
    is_debit_balance_normal,
    normal_balance_for_account_type,
)

# ============================================================================
# NormalBalance enum
# ============================================================================


class TestNormalBalanceEnum:
    def test_opposite(self):
        assert NormalBalance.DEBIT.opposite == NormalBalance.CREDIT
        assert NormalBalance.CREDIT.opposite == NormalBalance.DEBIT

    def test_sign(self):
        assert NormalBalance.DEBIT.sign == 1
        assert NormalBalance.CREDIT.sign == -1

    def test_is_debit_is_credit(self):
        assert NormalBalance.DEBIT.is_debit is True
        assert NormalBalance.DEBIT.is_credit is False
        assert NormalBalance.CREDIT.is_credit is True
        assert NormalBalance.CREDIT.is_debit is False

    def test_display_name(self):
        assert NormalBalance.DEBIT.display_name() == "Debit"
        assert NormalBalance.CREDIT.display_name() == "Kredit"

    def test_short_name(self):
        assert NormalBalance.DEBIT.short_name() == "D"
        assert NormalBalance.CREDIT.short_name() == "K"

    @pytest.mark.parametrize("raw", ["debit", "DEBIT", "d", "D"])
    def test_from_string_debit(self, raw):
        assert NormalBalance.from_string(raw) == NormalBalance.DEBIT

    @pytest.mark.parametrize("raw", ["credit", "CREDIT", "k", "c", "K", "C"])
    def test_from_string_credit(self, raw):
        assert NormalBalance.from_string(raw) == NormalBalance.CREDIT

    def test_from_string_invalid_returns_none(self):
        assert NormalBalance.from_string("nonsense") is None

    def test_from_sign_positive(self):
        assert NormalBalance.from_sign(1) == NormalBalance.DEBIT
        assert NormalBalance.from_sign(100) == NormalBalance.DEBIT

    def test_from_sign_negative(self):
        assert NormalBalance.from_sign(-1) == NormalBalance.CREDIT

    def test_from_sign_zero_returns_none(self):
        assert NormalBalance.from_sign(0) is None

    def test_to_increase_returns_amount_unchanged(self):
        assert NormalBalance.DEBIT.to_increase(100) == 100

    def test_to_decrease_negates_amount(self):
        assert NormalBalance.DEBIT.to_decrease(100) == -100


# ============================================================================
# AccountNormalBalanceVO
# ============================================================================


class TestAccountNormalBalanceVOConstruction:
    def test_valid_construction(self):
        vo = AccountNormalBalanceVO(NormalBalance.DEBIT)
        assert vo.normal_balance == NormalBalance.DEBIT

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid normal balance"):
            AccountNormalBalanceVO("debit")  # not a NormalBalance instance

    def test_balance_property_backward_compat(self):
        vo = AccountNormalBalanceVO(NormalBalance.CREDIT)
        assert vo.balance == NormalBalance.CREDIT

    def test_is_immutable(self):
        vo = AccountNormalBalanceVO(NormalBalance.DEBIT)
        with pytest.raises(Exception):
            vo.normal_balance = NormalBalance.CREDIT


class TestAccountNormalBalanceVOFactories:
    def test_debit_factory(self):
        vo = AccountNormalBalanceVO.debit()
        assert vo.normal_balance == NormalBalance.DEBIT

    def test_credit_factory(self):
        vo = AccountNormalBalanceVO.credit()
        assert vo.normal_balance == NormalBalance.CREDIT

    def test_from_string_valid(self):
        vo = AccountNormalBalanceVO.from_string("debit")
        assert vo.normal_balance == NormalBalance.DEBIT

    def test_from_string_invalid_returns_none(self):
        assert AccountNormalBalanceVO.from_string("bogus") is None


class TestAccountNormalBalanceVOBehaviour:
    def test_opposite(self):
        vo = AccountNormalBalanceVO.debit()
        assert vo.opposite == AccountNormalBalanceVO.credit()

    def test_sign(self):
        assert AccountNormalBalanceVO.debit().sign == 1
        assert AccountNormalBalanceVO.credit().sign == -1

    def test_is_debit_is_credit(self):
        assert AccountNormalBalanceVO.debit().is_debit is True
        assert AccountNormalBalanceVO.debit().is_credit is False
        assert AccountNormalBalanceVO.credit().is_credit is True

    def test_to_dict(self):
        vo = AccountNormalBalanceVO.debit()
        d = vo.to_dict()
        assert d == {
            "balance": "debit",
            "is_debit": True,
            "is_credit": False,
            "sign": 1,
            "display_name": "Debit",
            "short_name": "D",
        }

    def test_from_dict_round_trip(self):
        vo = AccountNormalBalanceVO.credit()
        restored = AccountNormalBalanceVO.from_dict(vo.to_dict())
        assert restored == vo

    def test_from_dict_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid balance in dict"):
            AccountNormalBalanceVO.from_dict({"balance": "bogus"})

    def test_str(self):
        assert str(AccountNormalBalanceVO.debit()) == "Debit"
        assert str(AccountNormalBalanceVO.credit()) == "Kredit"

    def test_repr(self):
        assert repr(AccountNormalBalanceVO.debit()) == "AccountNormalBalanceVO(debit)"

    def test_equality(self):
        assert AccountNormalBalanceVO.debit() == AccountNormalBalanceVO.debit()
        assert AccountNormalBalanceVO.debit() != AccountNormalBalanceVO.credit()

    def test_equality_with_non_vo_is_false(self):
        assert (AccountNormalBalanceVO.debit() == "debit") is False

    def test_hash_is_consistent_with_equality(self):
        a = AccountNormalBalanceVO.debit()
        b = AccountNormalBalanceVO.debit()
        assert hash(a) == hash(b)

    def test_usable_as_dict_key(self):
        d = {AccountNormalBalanceVO.debit(): "d", AccountNormalBalanceVO.credit(): "c"}
        assert d[AccountNormalBalanceVO.debit()] == "d"


# ============================================================================
# Module-level helpers
# ============================================================================


class TestNormalBalanceForAccountType:
    @pytest.mark.parametrize(
        "account_type, expected",
        [
            ("asset", NormalBalance.DEBIT),
            ("expense", NormalBalance.DEBIT),
            ("contra_asset", NormalBalance.CREDIT),
            ("contra_equity", NormalBalance.DEBIT),
            ("liability", NormalBalance.CREDIT),
            ("equity", NormalBalance.CREDIT),
            ("revenue", NormalBalance.CREDIT),
            ("contra_liability", NormalBalance.DEBIT),
            ("contra_revenue", NormalBalance.DEBIT),
        ],
    )
    def test_mapping(self, account_type, expected):
        vo = normal_balance_for_account_type(account_type)
        assert vo.normal_balance == expected

    def test_case_insensitive(self):
        vo = normal_balance_for_account_type("ASSET")
        assert vo.normal_balance == NormalBalance.DEBIT

    def test_unknown_type_defaults_to_debit(self):
        vo = normal_balance_for_account_type("unknown_type")
        assert vo.normal_balance == NormalBalance.DEBIT


class TestIsDebitCreditBalanceNormal:
    def test_is_debit_balance_normal_with_vo(self):
        assert is_debit_balance_normal(AccountNormalBalanceVO.debit()) is True
        assert is_debit_balance_normal(AccountNormalBalanceVO.credit()) is False

    def test_is_debit_balance_normal_with_string(self):
        assert is_debit_balance_normal("debit") is True
        assert is_debit_balance_normal("credit") is False

    def test_is_debit_balance_normal_with_enum(self):
        assert is_debit_balance_normal(NormalBalance.DEBIT) is True

    def test_is_credit_balance_normal_with_vo(self):
        assert is_credit_balance_normal(AccountNormalBalanceVO.credit()) is True
        assert is_credit_balance_normal(AccountNormalBalanceVO.debit()) is False

    def test_is_credit_balance_normal_with_string(self):
        assert is_credit_balance_normal("credit") is True

    def test_is_credit_balance_normal_with_enum(self):
        assert is_credit_balance_normal(NormalBalance.CREDIT) is True
