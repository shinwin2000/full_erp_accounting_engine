"""
Tests for domain/coa/invariants_validator.py

Covers ValidationResult, and every COAInvariantsValidator method (code/name
format, uniqueness, parent-child rules, cycle/depth checks, lifecycle
checks, opening balance rules, control account rules, cross-entity checks,
the composite validate_new_account/validate_existing_account_update, bulk
helpers, and additional business rules), plus the module-level convenience
functions.

======================================================================
KNOWN BUGS IN THE SOURCE (verified by direct execution):

BUG-COA-VALIDATOR-001 — `validate_opening_balance_sign(opening_balance,
normal_balance)` checks `if normal_balance == "debit"` (a literal string).
But every internal caller (`validate_new_account`,
`validate_existing_account_update`) passes `account.normal_balance`, which
is a `NormalBalance` ENUM instance (`NormalBalance.DEBIT` /
`NormalBalance.CREDIT`), never the string `"debit"`. Since an enum member
is never equal to a plain string, the `if` branch is never taken and the
function *always* evaluates the "credit" branch. Net effect: any normal,
valid DEBIT-normal account (Cash, AR, Inventory, Fixed Assets, Expenses --
the majority of a real chart of accounts) with a positive opening balance
is incorrectly reported as invalid ("Opening balance for credit account
cannot be positive"). Confirmed end-to-end: a plain Cash/ASSET/DEBIT
account with opening_balance=500 fails `validate_new_account()` with this
exact message.

BUG-COA-VALIDATOR-002 — `validate_opening_balance_precision()` checks
`opening_balance.as_tuple().exponent < -max_decimals`, i.e. it inspects
how the `Decimal` was literally constructed (its stored exponent), not
the actual numeric value. Separately, `AccountEntity.__post_init__`
*always* quantizes `opening_balance` to 2 decimal places (exponent -2)
regardless of currency (see BUG-ACCOUNT construction behavior in
test_account_entity.py). For zero-decimal currencies (IDR, JPY, KRW, VND;
`max_decimals=0`), this means `validate_opening_balance_precision()` will
ALWAYS report a failure for ANY real `AccountEntity` in that currency --
even `Decimal("0.00")` (logically zero) fails, since its exponent is -2,
not because the value has meaningful sub-unit precision.

Both bugs are confirmed together at the `validate_new_account()` level:
a bare, textbook-valid IDR Cash account with a positive balance fails
with *two* unrelated-sounding errors simultaneously.

Additionally, `ALLOWED_PARENT_TYPES` has no entries for
`AccountType.CONTRA_REVENUE` or `AccountType.CONTRA_EXPENSE` (only 8 of
the 10 AccountType members are mapped), so
`validate_parent_type_compatibility()` always reports "Unknown child
account type" for those two types regardless of the proposed parent.
======================================================================
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from domain.coa.account_code_vo import AccountCodeVO
from domain.coa.account_entity import AccountEntity
from domain.coa.account_normal_balance_vo import NormalBalance
from domain.coa.account_type_enum import AccountType
from domain.coa.invariants_validator import (
    COAInvariantsValidator,
    InvariantViolationError,
    ValidationResult,
    validate_account_code,
    validate_account_name,
)

# ============================================================================
# Reset shared ClassVar state (AccountEntity._audit_trail etc.)
# ============================================================================


@pytest.fixture(autouse=True)
def reset_class_level_state():
    AccountEntity._audit_trail.clear()
    AccountEntity._snapshots.clear()
    yield
    AccountEntity._audit_trail.clear()
    AccountEntity._snapshots.clear()


# ============================================================================
# ValidationResult
# ============================================================================


class TestValidationResult:
    def test_success_factory(self):
        result = ValidationResult.success()
        assert bool(result) is True
        assert result.message == "OK"

    def test_failure_factory(self):
        result = ValidationResult.failure("bad thing")
        assert bool(result) is False
        assert result.message == "bad thing"

    def test_str_uses_message_when_present(self):
        assert str(ValidationResult.failure("nope")) == "nope"

    def test_str_falls_back_when_no_message(self):
        assert str(ValidationResult(True, message=None)) == "Valid"
        assert str(ValidationResult(False, message=None)) == "Invalid"

    def test_details_default_empty(self):
        assert ValidationResult.success().details == {}


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def validator():
    return COAInvariantsValidator()


@pytest.fixture
def legal_entity_id():
    return uuid4()


def make_account(legal_entity_id, **overrides):
    defaults = dict(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        code=AccountCodeVO("1000"),
        name="Cash",
        account_type=AccountType.ASSET,
        normal_balance=NormalBalance.DEBIT,
    )
    defaults.update(overrides)
    return AccountEntity(**defaults)


# ============================================================================
# Code format & uniqueness
# ============================================================================


class TestValidateAccountCodeFormat:
    def test_valid_code(self, validator):
        assert bool(validator.validate_account_code_format("1000")) is True

    def test_empty_code_fails(self, validator):
        assert bool(validator.validate_account_code_format("")) is False

    def test_non_string_fails(self, validator):
        assert bool(validator.validate_account_code_format(None)) is False

    def test_too_long_fails(self, validator):
        assert bool(validator.validate_account_code_format("1" * 21)) is False

    def test_invalid_characters_fail(self, validator):
        assert bool(validator.validate_account_code_format("1000!")) is False

    def test_leading_separator_fails(self, validator):
        assert bool(validator.validate_account_code_format(".1000")) is False

    def test_trailing_separator_fails(self, validator):
        assert bool(validator.validate_account_code_format("1000.")) is False

    def test_dots_and_dashes_allowed(self, validator):
        assert bool(validator.validate_account_code_format("1.10-01")) is True


class TestValidateUniqueAccountCode:
    def test_unique_passes(self, validator):
        assert bool(validator.validate_unique_account_code("2000", {"1000"})) is True

    def test_duplicate_fails(self, validator):
        assert bool(validator.validate_unique_account_code("1000", {"1000"})) is False


# ============================================================================
# Name validation
# ============================================================================


class TestValidateAccountName:
    def test_valid_name(self, validator):
        assert bool(validator.validate_account_name("Cash")) is True

    def test_empty_fails(self, validator):
        assert bool(validator.validate_account_name("")) is False

    def test_too_short_fails(self, validator):
        assert bool(validator.validate_account_name("X")) is False

    def test_too_long_fails(self, validator):
        assert bool(validator.validate_account_name("A" * 201)) is False

    def test_exactly_200_chars_passes(self, validator):
        assert bool(validator.validate_account_name("A" * 200)) is True


# ============================================================================
# Parent-child validation
# ============================================================================


class TestValidateParentExists:
    def test_none_parent_is_valid(self, validator):
        assert bool(validator.validate_parent_exists(None, set())) is True

    def test_existing_parent_is_valid(self, validator):
        parent_id = uuid4()
        assert bool(validator.validate_parent_exists(parent_id, {parent_id})) is True

    def test_missing_parent_is_invalid(self, validator):
        assert bool(validator.validate_parent_exists(uuid4(), set())) is False


class TestValidateParentNotSelf:
    def test_different_ids_valid(self, validator):
        assert bool(validator.validate_parent_not_self(uuid4(), uuid4())) is True

    def test_none_parent_valid(self, validator):
        assert bool(validator.validate_parent_not_self(uuid4(), None)) is True

    def test_self_parent_invalid(self, validator):
        account_id = uuid4()
        assert bool(validator.validate_parent_not_self(account_id, account_id)) is False


class TestValidateParentTypeCompatibility:
    def test_asset_under_asset_valid(self, validator):
        assert bool(validator.validate_parent_type_compatibility(AccountType.ASSET, AccountType.ASSET)) is True

    def test_asset_under_liability_invalid(self, validator):
        assert bool(validator.validate_parent_type_compatibility(AccountType.ASSET, AccountType.LIABILITY)) is False

    def test_contra_asset_under_asset_valid(self, validator):
        assert bool(
            validator.validate_parent_type_compatibility(AccountType.CONTRA_ASSET, AccountType.ASSET)
        ) is True

    def test_contra_revenue_is_unmapped(self, validator):
        """CONTRA_REVENUE / CONTRA_EXPENSE have no entry in ALLOWED_PARENT_TYPES,
        so they are always reported as an unknown child type."""
        result = validator.validate_parent_type_compatibility(AccountType.CONTRA_REVENUE, AccountType.REVENUE)
        assert bool(result) is False
        assert "Unknown child account type" in result.message

    def test_contra_expense_is_unmapped(self, validator):
        result = validator.validate_parent_type_compatibility(AccountType.CONTRA_EXPENSE, AccountType.EXPENSE)
        assert bool(result) is False
        assert "Unknown child account type" in result.message


class TestValidateNoCycle:
    def test_none_new_parent_is_valid(self, validator):
        assert bool(validator.validate_no_cycle(uuid4(), None, lambda x: None)) is True

    def test_no_cycle_is_valid(self, validator):
        account_id = uuid4()
        new_parent_id = uuid4()
        grandparent_id = uuid4()
        parent_map = {new_parent_id: grandparent_id, grandparent_id: None}
        assert bool(validator.validate_no_cycle(account_id, new_parent_id, parent_map.get)) is True

    def test_direct_cycle_detected(self, validator):
        account_id = uuid4()
        parent_map = {account_id: None}
        assert bool(validator.validate_no_cycle(account_id, account_id, parent_map.get)) is False

    def test_indirect_cycle_detected(self, validator):
        account_id = uuid4()
        new_parent_id = uuid4()
        parent_map = {new_parent_id: account_id, account_id: None}
        assert bool(validator.validate_no_cycle(account_id, new_parent_id, parent_map.get)) is False


class TestValidateMaxDepth:
    def test_none_parent_is_valid(self, validator):
        assert bool(validator.validate_max_depth(None, lambda x: 0)) is True

    def test_within_max_depth_is_valid(self, validator):
        parent_id = uuid4()
        assert bool(validator.validate_max_depth(parent_id, lambda x: 5)) is True

    def test_exceeding_max_depth_is_invalid(self, validator):
        parent_id = uuid4()
        assert bool(validator.validate_max_depth(parent_id, lambda x: 10)) is False


# ============================================================================
# Account lifecycle validation
# ============================================================================


class TestValidateCanDeactivate:
    def test_inactive_account_cannot_be_deactivated_again(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)  # DRAFT, is_active False
        result = validator.validate_can_deactivate(account, children=[])
        assert bool(result) is False
        assert "already inactive" in result.message

    def test_active_account_with_no_active_children_can_deactivate(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        account = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_deactivate(account, children=[])
        assert bool(result) is True

    def test_account_with_active_children_cannot_deactivate(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        account = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        active_child = make_account(legal_entity_id, code=AccountCodeVO("1001"), status=AccountStatus.ACTIVE)
        result = validator.validate_can_deactivate(account, children=[active_child])
        assert bool(result) is False
        assert "active child account" in result.message

    def test_account_with_transactions_cannot_deactivate(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        account = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_deactivate(account, children=[], has_transactions=True)
        assert bool(result) is False


class TestValidateCanReactivate:
    def test_active_account_cannot_reactivate(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        account = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_reactivate(account)
        assert bool(result) is False
        assert "already active" in result.message

    def test_inactive_account_with_no_parent_can_reactivate(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)
        result = validator.validate_can_reactivate(account)
        assert bool(result) is True

    def test_inactive_account_with_inactive_parent_cannot_reactivate(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, parent_id=uuid4())
        result = validator.validate_can_reactivate(account, parent_active=False)
        assert bool(result) is False
        assert "parent account is inactive" in result.message


class TestValidateCanDelete:
    def test_account_with_children_cannot_delete(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)
        child = make_account(legal_entity_id, code=AccountCodeVO("1001"))
        result = validator.validate_can_delete(account, children=[child])
        assert bool(result) is False

    def test_account_with_transactions_cannot_delete(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)
        result = validator.validate_can_delete(account, children=[], has_transactions=True)
        assert bool(result) is False

    def test_active_account_cannot_delete(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        account = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_delete(account, children=[])
        assert bool(result) is False
        assert "Deactivate before deletion" in result.message

    def test_inactive_account_with_no_children_or_transactions_can_delete(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)  # DRAFT -> is_active False
        result = validator.validate_can_delete(account, children=[])
        assert bool(result) is True


# ============================================================================
# Opening balance validation (documented bugs)
# ============================================================================


class TestValidateOpeningBalanceSign:
    def test_debit_account_nonnegative_balance_valid_with_string(self, validator):
        result = validator.validate_opening_balance_sign(Decimal("100"), "debit")
        assert bool(result) is True

    def test_debit_account_negative_balance_invalid_with_string(self, validator):
        result = validator.validate_opening_balance_sign(Decimal("-1"), "debit")
        assert bool(result) is False

    def test_credit_account_nonpositive_balance_valid_with_string(self, validator):
        result = validator.validate_opening_balance_sign(Decimal("-100"), "credit")
        assert bool(result) is True

    def test_credit_account_positive_balance_invalid_with_string(self, validator):
        result = validator.validate_opening_balance_sign(Decimal("100"), "credit")
        assert bool(result) is False

    def test_debit_enum_with_positive_balance_incorrectly_fails(self, validator):
        """BUG-COA-VALIDATOR-001: passing NormalBalance.DEBIT (an enum, as
        every real caller does) instead of the literal string "debit"
        makes the function always take the credit branch, wrongly
        rejecting an entirely normal debit-side positive balance."""
        result = validator.validate_opening_balance_sign(Decimal("100"), NormalBalance.DEBIT)
        assert bool(result) is False
        assert "credit account cannot be positive" in result.message

    def test_credit_enum_still_correctly_rejects_positive_balance(self, validator):
        result = validator.validate_opening_balance_sign(Decimal("100"), NormalBalance.CREDIT)
        assert bool(result) is False


class TestValidateOpeningBalancePrecision:
    def test_zero_decimal_currency_accepts_whole_number(self, validator):
        result = validator.validate_opening_balance_precision(Decimal("500"), "IDR")
        assert bool(result) is True

    def test_zero_decimal_currency_rejects_quantized_value_even_if_logically_whole(self, validator):
        """BUG-COA-VALIDATOR-002: the check inspects the Decimal's stored
        exponent, not its logical value. AccountEntity always quantizes
        opening_balance to 2 decimals, so a real IDR account's balance
        (e.g. Decimal("500.00")) fails here even though 500.00 == 500."""
        result = validator.validate_opening_balance_precision(Decimal("500.00"), "IDR")
        assert bool(result) is False
        assert "Maximum allowed: 0" in result.message

    def test_two_decimal_currency_accepts_two_decimals(self, validator):
        result = validator.validate_opening_balance_precision(Decimal("100.50"), "USD")
        assert bool(result) is True

    def test_two_decimal_currency_rejects_three_decimals(self, validator):
        result = validator.validate_opening_balance_precision(Decimal("100.505"), "USD")
        assert bool(result) is False

    def test_unknown_currency_defaults_to_two_decimals(self, validator):
        result = validator.validate_opening_balance_precision(Decimal("100.50"), "XYZ")
        assert bool(result) is True

    def test_currency_code_is_case_insensitive(self, validator):
        result = validator.validate_opening_balance_precision(Decimal("100"), "idr")
        assert bool(result) is True


# ============================================================================
# Control account / legal entity validation
# ============================================================================


class TestValidateControlAccount:
    def test_control_account_without_children_still_succeeds(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, is_control_account=True)
        result = validator.validate_control_account(account, has_children=False)
        assert bool(result) is True  # only logs a debug warning, never fails

    def test_regular_account_always_succeeds(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)
        assert bool(validator.validate_control_account(account, has_children=True)) is True


class TestValidateSameLegalEntity:
    def test_matching_entities_valid(self, validator):
        le = uuid4()
        assert bool(validator.validate_same_legal_entity(le, le)) is True

    def test_mismatched_entities_invalid(self, validator):
        assert bool(validator.validate_same_legal_entity(uuid4(), uuid4())) is False


# ============================================================================
# Composite validations
# ============================================================================


class TestValidateNewAccount:
    def test_valid_debit_account_still_fails_due_to_documented_bugs(self, validator, legal_entity_id):
        """Demonstrates BUG-COA-VALIDATOR-001 and -002 together: a
        completely ordinary IDR Cash/ASSET/DEBIT account with a positive
        balance fails validate_new_account() with two unrelated-looking
        errors, even though nothing is actually wrong with the account."""
        account = make_account(legal_entity_id, opening_balance=Decimal("500"), currency_code="IDR")
        results = validator.validate_new_account(
            account, existing_codes=set(), existing_accounts={}, coa_legal_entity_id=legal_entity_id,
        )
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert any("credit account cannot be positive" in e for e in errors)
        assert any("Maximum allowed: 0" in e for e in errors)

    def test_zero_balance_account_avoids_sign_bug_but_hits_precision_check(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, opening_balance=Decimal("0"), currency_code="IDR")
        results = validator.validate_new_account(
            account, existing_codes=set(), existing_accounts={}, coa_legal_entity_id=legal_entity_id,
        )
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert any("Maximum allowed: 0" in e for e in errors)

    def test_duplicate_code_detected(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, opening_balance=Decimal("0"))
        results = validator.validate_new_account(
            account, existing_codes={"1000"}, existing_accounts={}, coa_legal_entity_id=legal_entity_id,
        )
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert any("already exists" in e for e in errors)

    def test_cross_legal_entity_detected(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, opening_balance=Decimal("0"))
        results = validator.validate_new_account(
            account, existing_codes=set(), existing_accounts={}, coa_legal_entity_id=uuid4(),
        )
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert any("does not match COA legal entity" in e for e in errors)


class TestValidateExistingAccountUpdate:
    def test_no_changes_only_checks_legal_entity(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, opening_balance=Decimal("0"))
        results = validator.validate_existing_account_update(
            old_account=account, new_account=account, existing_codes=set(),
            existing_accounts={}, get_parent_func=lambda x: None, get_depth_func=lambda x: 0,
            coa_legal_entity_id=legal_entity_id,
        )
        assert len(results) == 1  # only the legal-entity check runs
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is True

    def test_code_change_validated(self, validator, legal_entity_id):
        old = make_account(legal_entity_id, opening_balance=Decimal("0"))
        new = make_account(
            legal_entity_id, opening_balance=Decimal("0"), code=AccountCodeVO("2000"), id=old.id,
        )
        results = validator.validate_existing_account_update(
            old_account=old, new_account=new, existing_codes={"2000"},
            existing_accounts={}, get_parent_func=lambda x: None, get_depth_func=lambda x: 0,
            coa_legal_entity_id=legal_entity_id,
        )
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert any("already exists" in e for e in errors)

    def test_parent_change_cycle_detected(self, validator, legal_entity_id):
        old = make_account(legal_entity_id, opening_balance=Decimal("0"))
        new_parent_id = uuid4()
        new = make_account(
            legal_entity_id, opening_balance=Decimal("0"), parent_id=new_parent_id, id=old.id,
        )
        parent_map = {new_parent_id: old.id, old.id: None}
        results = validator.validate_existing_account_update(
            old_account=old, new_account=new, existing_codes=set(),
            existing_accounts={new_parent_id: make_account(legal_entity_id, code=AccountCodeVO("9000"))},
            get_parent_func=parent_map.get, get_depth_func=lambda x: 0,
            coa_legal_entity_id=legal_entity_id,
        )
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert any("cycle" in e for e in errors)


# ============================================================================
# Bulk validation helpers
# ============================================================================


class TestBulkHelpers:
    def test_validate_all_results_all_valid(self):
        results = [ValidationResult.success(), ValidationResult.success()]
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is True
        assert errors == []

    def test_validate_all_results_collects_errors(self):
        results = [ValidationResult.success(), ValidationResult.failure("bad 1"), ValidationResult.failure("bad 2")]
        valid, errors = COAInvariantsValidator.validate_all_results(results)
        assert valid is False
        assert errors == ["bad 1", "bad 2"]

    def test_raise_if_invalid_does_not_raise_when_all_valid(self):
        COAInvariantsValidator.raise_if_invalid([ValidationResult.success()])  # no raise

    def test_raise_if_invalid_raises_with_joined_messages(self):
        with pytest.raises(InvariantViolationError, match="bad 1; bad 2"):
            COAInvariantsValidator.raise_if_invalid(
                [ValidationResult.failure("bad 1"), ValidationResult.failure("bad 2")]
            )


# ============================================================================
# Additional business rules
# ============================================================================


class TestValidateAccountTypeConsistency:
    def test_asset_expects_debit(self, validator):
        assert bool(validator.validate_account_type_consistency(AccountType.ASSET, "debit")) is True

    def test_asset_with_credit_fails(self, validator):
        result = validator.validate_account_type_consistency(AccountType.ASSET, "credit")
        assert bool(result) is False

    def test_liability_expects_credit(self, validator):
        assert bool(validator.validate_account_type_consistency(AccountType.LIABILITY, "credit")) is True

    def test_unmapped_type_always_succeeds(self, validator):
        result = validator.validate_account_type_consistency(AccountType.CONTRA_REVENUE, "anything")
        assert bool(result) is True


class TestValidateCurrencySupported:
    def test_supported_currency(self, validator):
        assert bool(validator.validate_currency_supported("IDR")) is True

    def test_unsupported_currency(self, validator):
        assert bool(validator.validate_currency_supported("XXX")) is False

    def test_case_insensitive(self, validator):
        assert bool(validator.validate_currency_supported("usd")) is True


class TestValidateLevelConsistency:
    def test_matching_level(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, level=2)
        assert bool(validator.validate_level_consistency(account, expected_level=2)) is True

    def test_mismatched_level(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, level=2)
        result = validator.validate_level_consistency(account, expected_level=3)
        assert bool(result) is False
        assert "stored=2, expected=3" in result.message


# ============================================================================
# Module-level convenience functions
# ============================================================================


class TestConvenienceFunctions:
    def test_validate_account_code_true(self):
        assert validate_account_code("1000") is True

    def test_validate_account_code_false(self):
        assert validate_account_code("!!!") is False

    def test_validate_account_name_true(self):
        assert validate_account_name("Cash") is True

    def test_validate_account_name_false(self):
        assert validate_account_name("X") is False
