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
# Reset shared ClassVar state
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
# Code format & uniqueness (merged duplicates via parametrize)
# ============================================================================


class TestValidateAccountCodeFormat:
    @pytest.mark.parametrize("code,expected_valid", [
        ("1000", True),
        ("1.10-01", True),
        ("", False),
        (None, False),
        ("1" * 21, False),
        ("1000!", False),
        (".1000", False),
        ("1000.", False),
    ])
    def test_code_format(self, validator, code, expected_valid):
        result = validator.validate_account_code_format(code)
        assert bool(result) is expected_valid


class TestValidateUniqueAccountCode:
    @pytest.mark.parametrize("code,existing,expected_valid", [
        ("2000", {"1000"}, True),
        ("1000", {"1000"}, False),
    ])
    def test_uniqueness(self, validator, code, existing, expected_valid):
        result = validator.validate_unique_account_code(code, existing)
        assert bool(result) is expected_valid


# ============================================================================
# Name validation (merged duplicates)
# ============================================================================


class TestValidateAccountName:
    @pytest.mark.parametrize("name,expected_valid", [
        ("Cash", True),
        ("A" * 200, True),
        ("", False),
        ("X", False),  # too short
        ("A" * 201, False),  # too long
    ])
    def test_name_validation(self, validator, name, expected_valid):
        result = validator.validate_account_name(name)
        assert bool(result) is expected_valid


# ============================================================================
# Parent-child validation (merged duplicates)
# ============================================================================


class TestValidateParentExists:
    @pytest.mark.parametrize("parent_id,existing_ids,expected_valid", [
        (None, set(), True),
        (uuid4(), set(), False),   # parent_id not in existing_ids
    ])
    def test_parent_exists(self, validator, parent_id, existing_ids, expected_valid):
        result = validator.validate_parent_exists(parent_id, existing_ids)
        assert bool(result) is expected_valid

    def test_parent_exists_with_valid_parent(self, validator):
        parent_id = uuid4()
        existing_ids = {parent_id}
        result = validator.validate_parent_exists(parent_id, existing_ids)
        assert bool(result) is True


class TestValidateParentNotSelf:
    def test_parent_not_self(self, validator):
        account_id = uuid4()
        other = uuid4()
        assert bool(validator.validate_parent_not_self(account_id, other)) is True
        assert bool(validator.validate_parent_not_self(account_id, None)) is True
        assert bool(validator.validate_parent_not_self(account_id, account_id)) is False


class TestValidateParentTypeCompatibility:
    @pytest.mark.parametrize("child_type,parent_type,expected_valid", [
        (AccountType.ASSET, AccountType.ASSET, True),
        (AccountType.ASSET, AccountType.LIABILITY, False),
        (AccountType.CONTRA_ASSET, AccountType.ASSET, True),
        (AccountType.LIABILITY, AccountType.LIABILITY, True),
        (AccountType.CONTRA_LIABILITY, AccountType.LIABILITY, True),
        (AccountType.EQUITY, AccountType.EQUITY, True),
        (AccountType.CONTRA_EQUITY, AccountType.EQUITY, True),
        (AccountType.REVENUE, AccountType.REVENUE, True),
        (AccountType.EXPENSE, AccountType.EXPENSE, True),
        # Unmapped types (CONTRA_REVENUE, CONTRA_EXPENSE) always fail
        (AccountType.CONTRA_REVENUE, AccountType.REVENUE, False),
        (AccountType.CONTRA_EXPENSE, AccountType.EXPENSE, False),
    ])
    def test_parent_type_compatibility(self, validator, child_type, parent_type, expected_valid):
        result = validator.validate_parent_type_compatibility(child_type, parent_type)
        if not expected_valid:
            assert bool(result) is False
            # Check specific messages for unmapped types
            if child_type in (AccountType.CONTRA_REVENUE, AccountType.CONTRA_EXPENSE):
                assert "Unknown child account type" in result.message
        else:
            assert bool(result) is True


class TestValidateNoCycle:
    def test_no_cycle(self, validator):
        account_id = uuid4()
        new_parent_id = uuid4()
        grandparent_id = uuid4()
        parent_map = {new_parent_id: grandparent_id, grandparent_id: None}
        # no cycle
        assert bool(validator.validate_no_cycle(account_id, new_parent_id, parent_map.get)) is True
        # direct cycle
        parent_map_direct = {account_id: None}
        assert bool(validator.validate_no_cycle(account_id, account_id, parent_map_direct.get)) is False
        # indirect cycle
        parent_map_indirect = {new_parent_id: account_id, account_id: None}
        assert bool(validator.validate_no_cycle(account_id, new_parent_id, parent_map_indirect.get)) is False


class TestValidateMaxDepth:
    def test_max_depth(self, validator):
        parent_id = uuid4()
        # within max
        assert bool(validator.validate_max_depth(parent_id, lambda x: 5)) is True
        # at max (10) should fail because 10+1 > 10
        assert bool(validator.validate_max_depth(parent_id, lambda x: 10)) is False
        # None parent always valid
        assert bool(validator.validate_max_depth(None, lambda x: 0)) is True


# ============================================================================
# Account lifecycle validation
# ============================================================================


class TestValidateCanDeactivate:
    def test_can_deactivate(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        # already inactive
        inactive = make_account(legal_entity_id)
        result = validator.validate_can_deactivate(inactive, children=[])
        assert bool(result) is False
        assert "already inactive" in result.message

        # active, no active children, no transactions -> ok
        active = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_deactivate(active, children=[])
        assert bool(result) is True

        # active with active children -> fail
        active_child = make_account(legal_entity_id, code=AccountCodeVO("1001"), status=AccountStatus.ACTIVE)
        result = validator.validate_can_deactivate(active, children=[active_child])
        assert bool(result) is False
        assert "active child account" in result.message

        # active with transactions -> fail
        result = validator.validate_can_deactivate(active, children=[], has_transactions=True)
        assert bool(result) is False


class TestValidateCanReactivate:
    def test_can_reactivate(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        # already active
        active = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_reactivate(active)
        assert bool(result) is False
        assert "already active" in result.message

        # inactive, no parent -> ok
        inactive = make_account(legal_entity_id)
        result = validator.validate_can_reactivate(inactive)
        assert bool(result) is True

        # inactive with inactive parent -> fail
        inactive_with_parent = make_account(legal_entity_id, parent_id=uuid4())
        result = validator.validate_can_reactivate(inactive_with_parent, parent_active=False)
        assert bool(result) is False
        assert "parent account is inactive" in result.message


class TestValidateCanDelete:
    def test_can_delete(self, validator, legal_entity_id):
        from domain.coa.account_entity import AccountStatus

        inactive = make_account(legal_entity_id)  # DRAFT -> inactive
        # with children -> fail
        child = make_account(legal_entity_id, code=AccountCodeVO("1001"))
        result = validator.validate_can_delete(inactive, children=[child])
        assert bool(result) is False

        # with transactions -> fail
        result = validator.validate_can_delete(inactive, children=[], has_transactions=True)
        assert bool(result) is False

        # active -> fail
        active = make_account(legal_entity_id, status=AccountStatus.ACTIVE)
        result = validator.validate_can_delete(active, children=[])
        assert bool(result) is False
        assert "Deactivate before deletion" in result.message

        # inactive, no children, no transactions -> ok
        result = validator.validate_can_delete(inactive, children=[])
        assert bool(result) is True


# ============================================================================
# Opening balance validation (documented bugs)
# ============================================================================


class TestValidateOpeningBalanceSign:
    def test_with_string_normal_balance(self, validator):
        # These are the intended checks (using literal strings)
        assert bool(validator.validate_opening_balance_sign(Decimal("100"), "debit")) is True
        assert bool(validator.validate_opening_balance_sign(Decimal("-1"), "debit")) is False
        assert bool(validator.validate_opening_balance_sign(Decimal("-100"), "credit")) is True
        assert bool(validator.validate_opening_balance_sign(Decimal("100"), "credit")) is False

    def test_with_enum_normal_balance_bug(self, validator):
        """BUG-COA-VALIDATOR-001: passing NormalBalance.DEBIT enum causes
        the function to incorrectly treat the account as credit."""
        result = validator.validate_opening_balance_sign(Decimal("100"), NormalBalance.DEBIT)
        assert bool(result) is False
        assert "credit account cannot be positive" in result.message

        # Passing NormalBalance.CREDIT works correctly (still rejects positive)
        result = validator.validate_opening_balance_sign(Decimal("100"), NormalBalance.CREDIT)
        assert bool(result) is False


class TestValidateOpeningBalancePrecision:
    def test_precision_checks(self, validator):
        # IDR (0 decimals) accepts whole numbers
        assert bool(validator.validate_opening_balance_precision(Decimal("500"), "IDR")) is True

        # IDR rejects quantized values (bug)
        result = validator.validate_opening_balance_precision(Decimal("500.00"), "IDR")
        assert bool(result) is False
        assert "Maximum allowed: 0" in result.message

        # USD (2 decimals) accepts two decimals
        assert bool(validator.validate_opening_balance_precision(Decimal("100.50"), "USD")) is True

        # USD rejects three decimals
        result = validator.validate_opening_balance_precision(Decimal("100.505"), "USD")
        assert bool(result) is False

        # Unknown currency defaults to 2 decimals
        assert bool(validator.validate_opening_balance_precision(Decimal("100.50"), "XYZ")) is True

        # Case insensitive
        assert bool(validator.validate_opening_balance_precision(Decimal("100"), "idr")) is True


# ============================================================================
# Control account / legal entity validation
# ============================================================================


class TestValidateControlAccount:
    def test_control_account(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, is_control_account=True)
        # only logs warning, never fails
        assert bool(validator.validate_control_account(account, has_children=False)) is True
        assert bool(validator.validate_control_account(account, has_children=True)) is True

    def test_regular_account(self, validator, legal_entity_id):
        account = make_account(legal_entity_id)
        assert bool(validator.validate_control_account(account, has_children=True)) is True


class TestValidateSameLegalEntity:
    def test_same_legal_entity(self, validator):
        le = uuid4()
        assert bool(validator.validate_same_legal_entity(le, le)) is True
        assert bool(validator.validate_same_legal_entity(uuid4(), uuid4())) is False


# ============================================================================
# Composite validations
# ============================================================================


class TestValidateNewAccount:
    def test_valid_debit_account_still_fails_due_to_documented_bugs(self, validator, legal_entity_id):
        """Demonstrates BUG-COA-VALIDATOR-001 and -002 together."""
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
        existing_accounts = {new_parent_id: make_account(legal_entity_id, code=AccountCodeVO("9000"))}
        results = validator.validate_existing_account_update(
            old_account=old, new_account=new, existing_codes=set(),
            existing_accounts=existing_accounts,
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
        # Should not raise; we can simply call and verify no exception
        try:
            COAInvariantsValidator.raise_if_invalid([ValidationResult.success()])
        except Exception:
            pytest.fail("raise_if_invalid raised unexpectedly")

    def test_raise_if_invalid_raises_with_joined_messages(self):
        with pytest.raises(InvariantViolationError, match="bad 1; bad 2"):
            COAInvariantsValidator.raise_if_invalid(
                [ValidationResult.failure("bad 1"), ValidationResult.failure("bad 2")]
            )


# ============================================================================
# Additional business rules
# ============================================================================


class TestValidateAccountTypeConsistency:
    @pytest.mark.parametrize("account_type,normal_balance,expected_valid", [
        (AccountType.ASSET, "debit", True),
        (AccountType.ASSET, "credit", False),
        (AccountType.LIABILITY, "credit", True),
        (AccountType.LIABILITY, "debit", False),
        (AccountType.CONTRA_REVENUE, "anything", True),  # unmapped => always succeeds
    ])
    def test_type_consistency(self, validator, account_type, normal_balance, expected_valid):
        result = validator.validate_account_type_consistency(account_type, normal_balance)
        assert bool(result) is expected_valid


class TestValidateCurrencySupported:
    @pytest.mark.parametrize("currency,expected_valid", [
        ("IDR", True),
        ("USD", True),
        ("XXX", False),
        ("idr", True),
        ("usd", True),
    ])
    def test_currency_supported(self, validator, currency, expected_valid):
        result = validator.validate_currency_supported(currency)
        assert bool(result) is expected_valid


class TestValidateLevelConsistency:
    def test_level_consistency(self, validator, legal_entity_id):
        account = make_account(legal_entity_id, level=2)
        assert bool(validator.validate_level_consistency(account, expected_level=2)) is True
        result = validator.validate_level_consistency(account, expected_level=3)
        assert bool(result) is False
        assert "stored=2, expected=3" in result.message


# ============================================================================
# Module-level convenience functions
# ============================================================================


class TestConvenienceFunctions:
    @pytest.mark.parametrize("code,expected", [
        ("1000", True),
        ("!!!", False),
        ("", False),
    ])
    def test_validate_account_code(self, code, expected):
        assert validate_account_code(code) is expected

    @pytest.mark.parametrize("name,expected", [
        ("Cash", True),
        ("X", False),
        ("", False),
        ("A" * 200, True),
    ])
    def test_validate_account_name(self, name, expected):
        assert validate_account_name(name) is expected
