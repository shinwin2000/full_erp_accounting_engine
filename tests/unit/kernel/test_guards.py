#!/usr/bin/env python3

"""
Module: test_guards.py

Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk pre-condition guards (BalanceChecker, PeriodLockGuard, dll).

Dependencies:
    - kernel/guards/*.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from kernel.guards.authority_matrix import AuthorityMatrixGuard
from kernel.guards.balance_checker import BalanceChecker
from kernel.guards.budget_availability import BudgetAvailabilityGuard
from kernel.guards.credit_limit_enforcer import CreditLimitEnforcer
from kernel.guards.currency_validator import CurrencyValidator
from kernel.guards.legal_entity_boundary import LegalEntityBoundaryGuard
from kernel.guards.period_lock import PeriodLockGuard
from kernel.guards.sod_enforcer import SoDEnforcer


class TestBalanceChecker:
    """Test suite untuk BalanceChecker."""

    @pytest.fixture
    def balance_checker(self) -> BalanceChecker:
        return BalanceChecker()

    def test_balanced_journal_passes(self, balance_checker):
        context = {
            "journal_lines": [
                {"debit": Decimal("1000"), "credit": Decimal("0")},
                {"debit": Decimal("0"), "credit": Decimal("1000")},
            ]
        }
        errors = balance_checker.check(context)
        assert len(errors) == 0

    def test_unbalanced_journal_fails(self, balance_checker):
        context = {
            "journal_lines": [
                {"debit": Decimal("1000"), "credit": Decimal("0")},
                {"debit": Decimal("500"), "credit": Decimal("0")},
            ]
        }
        errors = balance_checker.check(context)
        assert len(errors) == 1
        assert "balance" in errors[0].lower()

    def test_no_lines_raises_error(self, balance_checker):
        context = {"journal_lines": []}
        errors = balance_checker.check(context)
        assert len(errors) == 1


class TestPeriodLockGuard:
    """Test suite untuk PeriodLockGuard."""

    @pytest.fixture
    def period_lock_guard(self):
        return PeriodLockGuard()

    def test_open_period_passes(self, period_lock_guard, mocker):
        # Mock service call
        mock_period_service = mocker.MagicMock()
        mock_period_service.get_period_status.return_value = "OPEN"
        period_lock_guard._period_service = mock_period_service
        context = {"legal_entity_id": uuid4(), "period": "2025-03"}
        errors = period_lock_guard.check(context)
        assert len(errors) == 0

    def test_closed_period_fails(self, period_lock_guard, mocker):
        mock_period_service = mocker.MagicMock()
        mock_period_service.get_period_status.return_value = "CLOSED"
        period_lock_guard._period_service = mock_period_service
        context = {"legal_entity_id": uuid4(), "period": "2024-12"}
        errors = period_lock_guard.check(context)
        assert len(errors) == 1
        assert "closed" in errors[0].lower()


class TestCurrencyValidator:
    """Test suite untuk CurrencyValidator."""

    @pytest.fixture
    def currency_validator(self):
        return CurrencyValidator()

    def test_valid_currency_passes(self, currency_validator):
        context = {"currency": "IDR"}
        errors = currency_validator.check(context)
        assert len(errors) == 0

    def test_invalid_currency_fails(self, currency_validator):
        context = {"currency": "XYZ"}
        errors = currency_validator.check(context)
        assert len(errors) == 1

    def test_missing_currency_uses_default(self, currency_validator):
        context = {}
        errors = currency_validator.check(context)
        assert len(errors) == 0  # default IDR


class TestLegalEntityBoundaryGuard:
    """Test suite untuk LegalEntityBoundaryGuard."""

    @pytest.fixture
    def boundary_guard(self):
        return LegalEntityBoundaryGuard()

    def test_same_entity_passes(self, boundary_guard, mocker):
        # 1. Buat satu UUID yang akan dipakai bersama
        entity_id = uuid4()

        # 2. Assign UUID tersebut ke nilai return COA mock
        mock_coa = mocker.MagicMock()
        mock_coa.get_account_legal_entity.return_value = entity_id
        boundary_guard._coa_service = mock_coa

        # 3. Gunakan UUID yang sama persis di dalam context
        context = {"legal_entity_id": entity_id, "journal_lines": [{"account_code": "1-1000"}]}

        errors = boundary_guard.check(context)
        assert len(errors) == 0

    def test_cross_entity_fails(self, boundary_guard, mocker):
        mock_coa = mocker.MagicMock()
        mock_coa.get_account_legal_entity.return_value = uuid4()  # berbeda
        boundary_guard._coa_service = mock_coa
        context = {"legal_entity_id": uuid4(), "journal_lines": [{"account_code": "1-1000"}]}
        errors = boundary_guard.check(context)
        assert len(errors) == 1


class TestAuthorityMatrixGuard:
    """Test suite untuk AuthorityMatrixGuard."""

    @pytest.fixture
    def authority_guard(self):
        return AuthorityMatrixGuard()

    def test_authorized_user_passes(self, authority_guard, mocker):
        mock_iam = mocker.MagicMock()
        mock_iam.has_permission.return_value = True
        authority_guard._iam_service = mock_iam
        context = {"user_id": uuid4(), "command_type": "PostJournalEntryCommand"}
        errors = authority_guard.check(context)
        assert len(errors) == 0

    def test_unauthorized_user_fails(self, authority_guard, mocker):
        mock_iam = mocker.MagicMock()
        mock_iam.has_permission.return_value = False
        authority_guard._iam_service = mock_iam
        context = {"user_id": uuid4(), "command_type": "PostJournalEntryCommand"}
        errors = authority_guard.check(context)
        assert len(errors) == 1


class TestSoDEnforcer:
    """Test suite untuk SoDEnforcer."""

    @pytest.fixture
    def sod_enforcer(self):
        return SoDEnforcer()

    def test_no_conflict_passes(self, sod_enforcer, mocker):
        mock_iam = mocker.MagicMock()
        mock_iam.check_sod_conflict.return_value = False
        sod_enforcer._iam_service = mock_iam
        context = {"user_id": uuid4(), "command_type": "PostJournalEntryCommand"}
        errors = sod_enforcer.check(context)
        assert len(errors) == 0

    def test_conflict_fails(self, sod_enforcer, mocker):
        mock_iam = mocker.MagicMock()
        mock_iam.check_sod_conflict.return_value = True
        sod_enforcer._iam_service = mock_iam
        context = {"user_id": uuid4(), "command_type": "ApproveJournalCommand"}
        errors = sod_enforcer.check(context)
        assert len(errors) == 1


class TestBudgetAvailabilityGuard:
    """Test suite untuk BudgetAvailabilityGuard."""

    @pytest.fixture
    def budget_guard(self):
        return BudgetAvailabilityGuard()

    def test_within_budget_passes(self, budget_guard, mocker):
        mock_budget = mocker.MagicMock()
        mock_budget.check_availability.return_value = True
        budget_guard._budget_service = mock_budget
        context = {
            "legal_entity_id": uuid4(),
            "journal_lines": [{"account_code": "5-1000", "debit": Decimal("5000")}],
        }
        errors = budget_guard.check(context)
        assert len(errors) == 0

    def test_exceeds_budget_fails(self, budget_guard, mocker):
        mock_budget = mocker.MagicMock()
        mock_budget.check_availability.return_value = False
        budget_guard._budget_service = mock_budget
        context = {
            "legal_entity_id": uuid4(),
            "journal_lines": [{"account_code": "5-1000", "debit": Decimal("100000000")}],
        }
        errors = budget_guard.check(context)
        assert len(errors) == 1


class TestCreditLimitEnforcer:
    """Test suite untuk CreditLimitEnforcer."""

    @pytest.fixture
    def credit_limit_guard(self):
        return CreditLimitEnforcer()

    def test_within_credit_limit_passes(self, credit_limit_guard, mocker):
        mock_customer = mocker.MagicMock()
        mock_customer.check_credit_limit.return_value = True
        credit_limit_guard._customer_service = mock_customer
        context = {"customer_id": uuid4(), "invoice_amount": Decimal("10000000")}
        errors = credit_limit_guard.check(context)
        assert len(errors) == 0

    def test_exceeds_credit_limit_fails(self, credit_limit_guard, mocker):
        mock_customer = mocker.MagicMock()
        mock_customer.check_credit_limit.return_value = False
        credit_limit_guard._customer_service = mock_customer
        context = {"customer_id": uuid4(), "invoice_amount": Decimal("1000000000")}
        errors = credit_limit_guard.check(context)
        assert len(errors) == 1


if __name__ == "__main__":
    pytest.main([__file__])
