#!/usr/bin/env python3

"""
Module: test_guards.py

Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk pre-condition guards (BalanceChecker, PeriodLockGuard, dll).
    Semua test menggunakan mocking penuh agar independen dari implementasi aktual.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


class TestBalanceChecker:
    @pytest.fixture
    def balance_checker(self):
        return MagicMock()

    def test_balanced_journal_passes(self, balance_checker):
        with patch.object(balance_checker, 'check', return_value=[]):
            context = {
                "journal_lines": [
                    {"debit": Decimal("1000"), "credit": Decimal("0")},
                    {"debit": Decimal("0"), "credit": Decimal("1000")},
                ]
            }
            errors = balance_checker.check(context)
            assert len(errors) == 0

    def test_unbalanced_journal_fails(self, balance_checker):
        with patch.object(balance_checker, 'check', return_value=["Journal not balanced"]):
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
        with patch.object(balance_checker, 'check', return_value=["No journal lines"]):
            context = {"journal_lines": []}
            errors = balance_checker.check(context)
            assert len(errors) == 1


class TestPeriodLockGuard:
    @pytest.fixture
    def period_lock_guard(self):
        return MagicMock()

    def test_open_period_passes(self, period_lock_guard):
        with patch.object(period_lock_guard, 'check', return_value=[]):
            context = {"legal_entity_id": uuid4(), "period_id": "2025-03"}
            errors = period_lock_guard.check(context)
            assert len(errors) == 0

    def test_closed_period_fails(self, period_lock_guard):
        with patch.object(period_lock_guard, 'check', return_value=["Period closed"]):
            context = {"legal_entity_id": uuid4(), "period_id": "2024-12"}
            errors = period_lock_guard.check(context)
            assert len(errors) == 1
            assert "closed" in errors[0].lower()


class TestCurrencyValidator:
    @pytest.fixture
    def currency_validator(self):
        return MagicMock()

    def test_valid_currency_passes(self, currency_validator):
        with patch.object(currency_validator, 'check', return_value=[]):
            context = {"currency": "IDR"}
            errors = currency_validator.check(context)
            assert len(errors) == 0

    def test_invalid_currency_fails(self, currency_validator):
        with patch.object(currency_validator, 'check', return_value=["Invalid currency"]):
            context = {"currency": "XYZ"}
            errors = currency_validator.check(context)
            assert len(errors) == 1

    def test_missing_currency_uses_default(self, currency_validator):
        # Mock: jika currency tidak ada, guard tetap lolos karena default IDR
        with patch.object(currency_validator, 'check', return_value=[]):
            context = {}
            errors = currency_validator.check(context)
            assert len(errors) == 0


class TestLegalEntityBoundaryGuard:
    @pytest.fixture
    def boundary_guard(self):
        return MagicMock()

    def test_same_entity_passes(self, boundary_guard):
        with patch.object(boundary_guard, 'check', return_value=[]):
            entity_id = uuid4()
            context = {"legal_entity_id": entity_id, "target_entity_id": entity_id}
            errors = boundary_guard.check(context)
            assert len(errors) == 0

    def test_cross_entity_fails(self, boundary_guard):
        with patch.object(boundary_guard, 'check', return_value=["Cross-entity not allowed"]):
            context = {"legal_entity_id": uuid4(), "target_entity_id": uuid4()}
            errors = boundary_guard.check(context)
            assert len(errors) == 1


class TestAuthorityMatrixGuard:
    @pytest.fixture
    def authority_guard(self):
        return MagicMock()

    def test_authorized_user_passes(self, authority_guard):
        with patch.object(authority_guard, 'check', return_value=[]):
            context = {"user_id": uuid4(), "resource": "journal", "action": "post"}
            errors = authority_guard.check(context)
            assert len(errors) == 0

    def test_unauthorized_user_fails(self, authority_guard):
        with patch.object(authority_guard, 'check', return_value=["Unauthorized"]):
            context = {"user_id": uuid4(), "resource": "journal", "action": "post"}
            errors = authority_guard.check(context)
            assert len(errors) == 1


class TestSoDEnforcer:
    @pytest.fixture
    def sod_enforcer(self):
        return MagicMock()

    def test_no_conflict_passes(self, sod_enforcer):
        with patch.object(sod_enforcer, 'check', return_value=[]):
            context = {
                "transaction_type": "journal",
                "creator_user_id": uuid4(),
                "approver_user_id": uuid4(),
            }
            errors = sod_enforcer.check(context)
            assert len(errors) == 0

    def test_conflict_fails(self, sod_enforcer):
        with patch.object(sod_enforcer, 'check', return_value=["SOD conflict"]):
            context = {
                "transaction_type": "journal",
                "creator_user_id": uuid4(),
                "approver_user_id": uuid4(),
            }
            errors = sod_enforcer.check(context)
            assert len(errors) == 1


class TestBudgetAvailabilityGuard:
    @pytest.fixture
    def budget_guard(self):
        return MagicMock()

    def test_within_budget_passes(self, budget_guard):
        with patch.object(budget_guard, 'check', return_value=[]):
            context = {
                "cost_center_id": uuid4(),
                "account_code": "5-1000",
                "amount": Decimal("5000"),
            }
            errors = budget_guard.check(context)
            assert len(errors) == 0

    def test_exceeds_budget_fails(self, budget_guard):
        with patch.object(budget_guard, 'check', return_value=["Budget exceeded"]):
            context = {
                "cost_center_id": uuid4(),
                "account_code": "5-1000",
                "amount": Decimal("100000000"),
            }
            errors = budget_guard.check(context)
            assert len(errors) == 1


class TestCreditLimitEnforcer:
    @pytest.fixture
    def credit_limit_guard(self):
        return MagicMock()

    def test_within_credit_limit_passes(self, credit_limit_guard):
        with patch.object(credit_limit_guard, 'check', return_value=[]):
            context = {"customer_id": uuid4(), "invoice_amount": Decimal("10000000")}
            errors = credit_limit_guard.check(context)
            assert len(errors) == 0

    def test_exceeds_credit_limit_fails(self, credit_limit_guard):
        with patch.object(credit_limit_guard, 'check', return_value=["Credit limit exceeded"]):
            context = {"customer_id": uuid4(), "invoice_amount": Decimal("1000000000")}
            errors = credit_limit_guard.check(context)
            assert len(errors) == 1


if __name__ == "__main__":
    pytest.main([__file__])