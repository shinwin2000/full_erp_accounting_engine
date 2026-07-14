"""
Tests for domain/coa/invariants.py

This module is a library of COA-specific exceptions, all deriving from
COAInvariantError. Tests cover the base exception's formatting/serialization
behavior and, for every concrete subclass, that its message is built
correctly, its extra attributes are stored, and its `details` dict is
populated as expected.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from domain.coa.invariants import (
    AccountAlreadyExistsError,
    AccountArchivedError,
    AccountCodeDuplicateError,
    AccountHasChildrenError,
    AccountLockedError,
    AccountNameEmptyError,
    AccountNameTooLongError,
    AccountNotActiveError,
    AccountNotFoundError,
    CannotDeactivateControlAccountError,
    CannotDeleteAccountWithTransactionsError,
    CircularParentReferenceError,
    COAAlreadyExistsError,
    COAArchivedError,
    COAInvariantError,
    COALockedError,
    COANotActiveError,
    COANotFoundError,
    CrossLegalEntityError,
    CurrencyMismatchError,
    InsufficientRoleError,
    InvalidAccountCodeError,
    InvalidNormalBalanceError,
    InvalidParentTypeError,
    InvalidStatusTransitionError,
    MaxHierarchyDepthExceededError,
    OpeningBalanceSignError,
    ParentAccountNotFoundError,
    ParentNotActiveError,
    SelfParentError,
)

# ============================================================================
# Base COAInvariantError
# ============================================================================


class TestCOAInvariantErrorBase:
    def test_default_code_is_class_name(self):
        exc = COAInvariantError("something went wrong")
        assert exc.code == "COAInvariantError"

    def test_custom_code_is_used(self):
        exc = COAInvariantError("bad thing", code="CUSTOM_CODE")
        assert exc.code == "CUSTOM_CODE"

    def test_details_default_to_empty_dict(self):
        exc = COAInvariantError("bad thing")
        assert exc.details == {}

    def test_message_includes_timestamp(self):
        exc = COAInvariantError("bad thing")
        assert "bad thing" in str(exc)
        assert str(exc.timestamp.year) in str(exc)

    def test_message_includes_details_when_present(self):
        exc = COAInvariantError("bad thing", details={"key": "value"})
        assert "Details:" in str(exc)
        assert "key" in str(exc)

    def test_to_dict(self):
        exc = COAInvariantError("bad thing", code="X", details={"a": 1})
        d = exc.to_dict()
        assert d["type"] == "COAInvariantError"
        assert d["code"] == "X"
        assert d["message"] == "bad thing"
        assert d["details"] == {"a": 1}
        assert "timestamp" in d

    def test_to_json_is_valid_json(self):
        import json

        exc = COAInvariantError("bad thing")
        parsed = json.loads(exc.to_json())
        assert parsed["message"] == "bad thing"

    def test_from_dict_round_trip(self):
        exc = COAInvariantError("bad thing", code="X", details={"a": 1})
        restored = COAInvariantError.from_dict(exc.to_dict())
        assert restored.message == "bad thing"
        assert restored.code == "X"
        assert restored.details == {"a": 1}

    def test_is_exception_subclass(self):
        assert issubclass(COAInvariantError, Exception)


# ============================================================================
# Code & Name Validation Errors
# ============================================================================


class TestInvalidAccountCodeError:
    def test_message_and_attributes(self):
        exc = InvalidAccountCodeError("ABC", "must be numeric", pattern=r"^[0-9]+$")
        assert "ABC" in str(exc)
        assert "must be numeric" in str(exc)
        assert exc.account_code == "ABC"
        assert exc.code == "INVALID_ACCOUNT_CODE"
        assert exc.details["pattern"] == r"^[0-9]+$"


class TestAccountCodeDuplicateError:
    def test_message_and_details(self):
        existing_id = uuid4()
        exc = AccountCodeDuplicateError("1000", existing_account_id=existing_id)
        assert "1000" in str(exc)
        assert exc.code == "DUPLICATE_ACCOUNT_CODE"
        assert exc.details["existing_account_id"] == str(existing_id)

    def test_none_existing_account_id(self):
        exc = AccountCodeDuplicateError("1000")
        assert exc.details["existing_account_id"] is None


class TestAccountNameTooLongError:
    def test_default_max_length(self):
        long_name = "A" * 250
        exc = AccountNameTooLongError(long_name)
        assert exc.max_length == 200
        assert exc.details["length"] == 250
        assert exc.code == "ACCOUNT_NAME_TOO_LONG"

    def test_custom_max_length(self):
        exc = AccountNameTooLongError("Some Name", max_length=10)
        assert exc.max_length == 10
        assert "10" in str(exc)


class TestAccountNameEmptyError:
    def test_message(self):
        exc = AccountNameEmptyError()
        assert "cannot be empty" in str(exc)
        assert exc.code == "ACCOUNT_NAME_EMPTY"


# ============================================================================
# Parent-Child Hierarchy Errors
# ============================================================================


class TestParentAccountNotFoundError:
    def test_message_and_details(self):
        parent_id = uuid4()
        exc = ParentAccountNotFoundError(parent_id)
        assert str(parent_id) in str(exc)
        assert exc.code == "PARENT_NOT_FOUND"
        assert exc.details["parent_id"] == str(parent_id)


class TestCircularParentReferenceError:
    def test_message_and_details(self):
        account_id, parent_id = uuid4(), uuid4()
        exc = CircularParentReferenceError(account_id, parent_id)
        assert "cycle" in str(exc)
        assert exc.code == "CIRCULAR_REFERENCE"
        assert exc.account_id == account_id
        assert exc.parent_id == parent_id


class TestAccountHasChildrenError:
    def test_message_and_details(self):
        account_id = uuid4()
        exc = AccountHasChildrenError(account_id, child_count=3)
        assert "3 child account(s)" in str(exc)
        assert exc.code == "ACCOUNT_HAS_CHILDREN"
        assert exc.child_count == 3


class TestInvalidParentTypeError:
    def test_message_without_allowed_types(self):
        exc = InvalidParentTypeError("asset", "revenue")
        assert "asset" in str(exc)
        assert "revenue" in str(exc)
        assert "Allowed parent types" not in str(exc)

    def test_message_with_allowed_types(self):
        exc = InvalidParentTypeError("asset", "revenue", allowed_parent_types=["asset", "liability"])
        assert "Allowed parent types: asset, liability" in str(exc)
        assert exc.code == "INVALID_PARENT_TYPE"


class TestMaxHierarchyDepthExceededError:
    def test_message_and_details(self):
        exc = MaxHierarchyDepthExceededError(current_depth=10, max_depth=10)
        assert "maximum of 10" in str(exc)
        assert exc.details["current_depth"] == 10
        assert exc.code == "MAX_HIERARCHY_DEPTH_EXCEEDED"


class TestSelfParentError:
    def test_message(self):
        account_id = uuid4()
        exc = SelfParentError(account_id)
        assert "own parent" in str(exc)
        assert exc.code == "SELF_PARENT"


class TestParentNotActiveError:
    def test_message_and_details(self):
        parent_id = uuid4()
        exc = ParentNotActiveError(parent_id, parent_status="suspended")
        assert "not active" in str(exc)
        assert "suspended" in str(exc)
        assert exc.code == "PARENT_NOT_ACTIVE"


# ============================================================================
# Account Status & Operation Errors
# ============================================================================


class TestCannotDeleteAccountWithTransactionsError:
    def test_message(self):
        account_id = uuid4()
        exc = CannotDeleteAccountWithTransactionsError(account_id, transaction_count=42)
        assert "42 transaction(s)" in str(exc)
        assert exc.code == "ACCOUNT_HAS_TRANSACTIONS"


class TestCannotDeactivateControlAccountError:
    def test_message(self):
        account_id = uuid4()
        exc = CannotDeactivateControlAccountError(account_id, child_count=2)
        assert "control account" in str(exc)
        assert exc.code == "CONTROL_ACCOUNT_HAS_CHILDREN"


class TestAccountLockedError:
    def test_message_with_reason(self):
        account_id = uuid4()
        exc = AccountLockedError(account_id, reason="fraud investigation")
        assert "is locked" in str(exc)
        assert "fraud investigation" in str(exc)
        assert exc.code == "ACCOUNT_LOCKED"

    def test_message_without_reason(self):
        account_id = uuid4()
        exc = AccountLockedError(account_id)
        assert str(account_id) in str(exc)
        assert exc.reason is None


class TestAccountArchivedError:
    def test_message(self):
        account_id = uuid4()
        exc = AccountArchivedError(account_id)
        assert "archived" in str(exc)
        assert exc.code == "ACCOUNT_ARCHIVED"


class TestAccountAlreadyExistsError:
    def test_message_with_code(self):
        account_id = uuid4()
        exc = AccountAlreadyExistsError(account_id, account_code="1000")
        assert "code='1000'" in str(exc)
        assert exc.code == "ACCOUNT_ALREADY_EXISTS"

    def test_message_without_code(self):
        account_id = uuid4()
        exc = AccountAlreadyExistsError(account_id)
        assert exc.account_code is None


class TestAccountNotFoundError:
    def test_message_with_uuid(self):
        account_id = uuid4()
        exc = AccountNotFoundError(account_id)
        assert str(account_id) in str(exc)
        assert exc.code == "ACCOUNT_NOT_FOUND"

    def test_message_with_string_id(self):
        exc = AccountNotFoundError("acc-123")
        assert "acc-123" in str(exc)


class TestAccountNotActiveError:
    def test_message(self):
        account_id = uuid4()
        exc = AccountNotActiveError(account_id, current_status="draft")
        assert "draft" in str(exc)
        assert "required: ACTIVE" in str(exc)
        assert exc.code == "ACCOUNT_NOT_ACTIVE"


# ============================================================================
# COA Level Errors
# ============================================================================


class TestCOALockedError:
    def test_message_with_reason(self):
        coa_id = uuid4()
        exc = COALockedError(coa_id, reason="year-end")
        assert "locked" in str(exc)
        assert "year-end" in str(exc)
        assert exc.code == "COA_LOCKED"


class TestCOAArchivedError:
    def test_message(self):
        coa_id = uuid4()
        exc = COAArchivedError(coa_id)
        assert "archived" in str(exc)
        assert exc.code == "COA_ARCHIVED"


class TestCOANotFoundError:
    def test_message(self):
        coa_id = uuid4()
        exc = COANotFoundError(coa_id)
        assert str(coa_id) in str(exc)
        assert exc.code == "COA_NOT_FOUND"


class TestCOAAlreadyExistsError:
    def test_message_with_name(self):
        legal_entity_id = uuid4()
        exc = COAAlreadyExistsError(legal_entity_id, coa_name="Main COA")
        assert "Main COA" in str(exc)
        assert exc.code == "COA_ALREADY_EXISTS"

    def test_message_without_name(self):
        legal_entity_id = uuid4()
        exc = COAAlreadyExistsError(legal_entity_id)
        assert exc.coa_name is None


class TestCOANotActiveError:
    def test_message_defaults_required_status_active(self):
        coa_id = uuid4()
        exc = COANotActiveError(coa_id, current_status="locked")
        assert "not ACTIVE" in str(exc)
        assert "current: locked" in str(exc)
        assert exc.required_status == "ACTIVE"

    def test_message_with_custom_required_status(self):
        coa_id = uuid4()
        exc = COANotActiveError(coa_id, current_status="draft", required_status="APPROVED")
        assert "not APPROVED" in str(exc)


# ============================================================================
# Currency & Balance Errors
# ============================================================================


class TestCurrencyMismatchError:
    def test_message(self):
        exc = CurrencyMismatchError(expected_currency="IDR", actual_currency="USD")
        assert "expected 'IDR'" in str(exc)
        assert "got 'USD'" in str(exc)
        assert exc.code == "CURRENCY_MISMATCH"


class TestOpeningBalanceSignError:
    def test_message(self):
        exc = OpeningBalanceSignError(account_code="1000", opening_balance="-100", normal_balance="debit")
        assert "1000" in str(exc)
        assert "-100" in str(exc)
        assert exc.code == "OPENING_BALANCE_SIGN_ERROR"


class TestInvalidNormalBalanceError:
    def test_message(self):
        exc = InvalidNormalBalanceError("upside_down", valid_values=["debit", "credit"])
        assert "upside_down" in str(exc)
        assert "debit, credit" in str(exc)
        assert exc.code == "INVALID_NORMAL_BALANCE"


# ============================================================================
# Legal Entity Errors
# ============================================================================


class TestCrossLegalEntityError:
    def test_message(self):
        account_le, coa_le = uuid4(), uuid4()
        exc = CrossLegalEntityError(account_le, coa_le)
        assert str(account_le) in str(exc)
        assert str(coa_le) in str(exc)
        assert exc.code == "CROSS_LEGAL_ENTITY"


# ============================================================================
# Transition & Approval Errors
# ============================================================================


class TestInvalidStatusTransitionError:
    def test_message_without_roles(self):
        exc = InvalidStatusTransitionError("draft", "posted")
        assert "draft to posted" in str(exc)
        assert "Required roles" not in str(exc)

    def test_message_with_roles(self):
        exc = InvalidStatusTransitionError("draft", "posted", required_roles=["admin"])
        assert "Required roles: admin" in str(exc)
        assert exc.code == "INVALID_STATUS_TRANSITION"


class TestInsufficientRoleError:
    def test_message(self):
        exc = InsufficientRoleError("user", required_roles=["admin", "auditor"], operation="lock account")
        assert "User role 'user' insufficient for lock account" in str(exc)
        assert "admin, auditor" in str(exc)
        assert exc.code == "INSUFFICIENT_ROLE"


# ============================================================================
# All subclasses share COAInvariantError's serialization behavior
# ============================================================================


class TestAllSubclassesAreCOAInvariantErrors:
    @pytest.mark.parametrize(
        "exc",
        [
            InvalidAccountCodeError("1", "bad"),
            AccountCodeDuplicateError("1"),
            AccountNameTooLongError("x"),
            AccountNameEmptyError(),
            ParentAccountNotFoundError(uuid4()),
            CircularParentReferenceError(uuid4(), uuid4()),
            AccountHasChildrenError(uuid4(), 1),
            InvalidParentTypeError("a", "b"),
            MaxHierarchyDepthExceededError(1, 1),
            SelfParentError(uuid4()),
            ParentNotActiveError(uuid4(), "draft"),
            CannotDeleteAccountWithTransactionsError(uuid4(), 1),
            CannotDeactivateControlAccountError(uuid4(), 1),
            AccountLockedError(uuid4()),
            AccountArchivedError(uuid4()),
            AccountAlreadyExistsError(uuid4()),
            AccountNotFoundError(uuid4()),
            AccountNotActiveError(uuid4(), "draft"),
            COALockedError(uuid4()),
            COAArchivedError(uuid4()),
            COANotFoundError(uuid4()),
            COAAlreadyExistsError(uuid4()),
            COANotActiveError(uuid4(), "draft"),
            CurrencyMismatchError("IDR", "USD"),
            OpeningBalanceSignError("1000", "-1", "debit"),
            InvalidNormalBalanceError("x", ["debit", "credit"]),
            CrossLegalEntityError(uuid4(), uuid4()),
            InvalidStatusTransitionError("a", "b"),
            InsufficientRoleError("user", ["admin"], "op"),
        ],
    )
    def test_is_coa_invariant_error_and_has_valid_to_dict(self, exc):
        assert isinstance(exc, COAInvariantError)
        d = exc.to_dict()
        assert d["type"] == type(exc).__name__
        assert "timestamp" in d
        assert isinstance(d["details"], dict)
