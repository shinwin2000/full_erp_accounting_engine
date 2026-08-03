"""
Tests for domain/coa/state_machine.py

Covers AccountStatus enum (helper predicates, display_name, from_string),
ALLOWED_TRANSITIONS map + get_allowed_transitions/is_transition_allowed/
get_required_roles, AccountStateMachine (can_transition/validate_transition/
transition/can_activate/can_suspend/can_lock/can_close/can_archive),
StatusTransitionRecord, TransitionHistory, COAStatus/COAStateMachine, and
module-level helpers.

======================================================================
KNOWN BUG IN THE SOURCE (verified by direct execution):

BUG-COA-SM-001 — `domain/coa/state_machine.py` defines its OWN
`AccountStatus` enum, which is a *different class* from
`domain.coa.account_entity.AccountStatus` even though both have the same
name and the same string values ("draft", "active", ...). They are NOT
equal or interchangeable (`state_machine.AccountStatus.DRAFT ==
account_entity.AccountStatus.DRAFT` is `False`). Every real
`AccountEntity` built via `account_entity.py` has a `.status` that is an
instance of `account_entity.AccountStatus`, which has NO `is_terminal()`
method (only `state_machine.AccountStatus` does). Consequently, calling
`AccountStateMachine.validate_transition(real_account, ...)` -- and
therefore also `.transition()`, `.can_activate()`, `.can_suspend()`,
`.can_lock()`, `.can_close()`, `.can_archive()`, all of which delegate to
`validate_transition()` -- immediately raises
`AttributeError: 'AccountStatus' object has no attribute 'is_terminal'`
for any real `AccountEntity`. This state machine can only be exercised
today with a stand-in object whose `.status` attribute is explicitly an
instance of `state_machine.AccountStatus` -- confirmed below with both a
passing stub-based test and a failing real-`AccountEntity`-based test.
======================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from domain.coa.state_machine import (
    ALLOWED_TRANSITIONS,
    AccountStateMachine,
    AccountStatus,
    COAStateMachine,
    COAStatus,
    StatusTransitionRecord,
    TransitionHistory,
    get_allowed_transitions,
    get_required_roles,
    get_status_display_name,
    is_active_to_status,
    is_transition_allowed,
    status_from_is_active,
)

# ============================================================================
# AccountStatus enum
# ============================================================================


class TestAccountStatus:
    def test_is_active(self):
        assert AccountStatus.ACTIVE.is_active() is True
        assert AccountStatus.DRAFT.is_active() is False

    def test_is_draft(self):
        assert AccountStatus.DRAFT.is_draft() is True

    def test_is_suspended(self):
        assert AccountStatus.SUSPENDED.is_suspended() is True

    def test_is_locked(self):
        assert AccountStatus.LOCKED.is_locked() is True

    def test_is_closed(self):
        assert AccountStatus.CLOSED.is_closed() is True

    def test_is_archived(self):
        assert AccountStatus.ARCHIVED.is_archived() is True

    def test_can_modify(self):
        assert AccountStatus.DRAFT.can_modify() is True
        assert AccountStatus.ACTIVE.can_modify() is True
        assert AccountStatus.SUSPENDED.can_modify() is True
        assert AccountStatus.LOCKED.can_modify() is False
        assert AccountStatus.CLOSED.can_modify() is False

    def test_can_post_only_active(self):
        assert AccountStatus.ACTIVE.can_post() is True
        assert AccountStatus.SUSPENDED.can_post() is False

    def test_can_delete(self):
        assert AccountStatus.DRAFT.can_delete() is True
        assert AccountStatus.CLOSED.can_delete() is True
        assert AccountStatus.ARCHIVED.can_delete() is True
        assert AccountStatus.ACTIVE.can_delete() is False

    def test_is_terminal(self):
        assert AccountStatus.CLOSED.is_terminal() is True
        assert AccountStatus.ARCHIVED.is_terminal() is True
        assert AccountStatus.ACTIVE.is_terminal() is False

    def test_display_name(self):
        assert AccountStatus.DRAFT.display_name() == "Draft"
        assert AccountStatus.ACTIVE.display_name() == "Aktif"
        assert AccountStatus.CLOSED.display_name() == "Ditutup"

    def test_from_string_valid(self):
        assert AccountStatus.from_string("active") == AccountStatus.ACTIVE
        assert AccountStatus.from_string("ACTIVE") == AccountStatus.ACTIVE

    def test_from_string_invalid_returns_none(self):
        assert AccountStatus.from_string("bogus") is None


# ============================================================================
# ALLOWED_TRANSITIONS / module helpers
# ============================================================================


class TestTransitionMapHelpers:
    def test_get_allowed_transitions_from_draft(self):
        result = set(get_allowed_transitions(AccountStatus.DRAFT))
        assert result == {AccountStatus.ACTIVE, AccountStatus.CLOSED, AccountStatus.ARCHIVED}

    def test_get_allowed_transitions_from_archived_is_empty(self):
        assert get_allowed_transitions(AccountStatus.ARCHIVED) == []

    def test_is_transition_allowed_true(self):
        assert is_transition_allowed(AccountStatus.DRAFT, AccountStatus.ACTIVE) is True

    def test_is_transition_allowed_false(self):
        assert is_transition_allowed(AccountStatus.DRAFT, AccountStatus.LOCKED) is False

    def test_get_required_roles_known_transition(self):
        roles = get_required_roles(AccountStatus.ACTIVE, AccountStatus.LOCKED)
        assert roles == {"auditor", "admin"}

    def test_get_required_roles_unknown_transition_is_empty(self):
        assert get_required_roles(AccountStatus.DRAFT, AccountStatus.LOCKED) == set()

    def test_closed_only_transitions_to_archived(self):
        assert get_allowed_transitions(AccountStatus.CLOSED) == [AccountStatus.ARCHIVED]

    def test_allowed_transitions_map_has_no_self_loops(self):
        for (frm, to) in ALLOWED_TRANSITIONS:
            assert frm != to


# ============================================================================
# AccountStateMachine — fixtures
# ============================================================================


@dataclass
class StubAccount:
    """A minimal stand-in whose `.status` is deliberately the
    state_machine's own AccountStatus (see BUG-COA-SM-001 for why a real
    AccountEntity cannot be used with AccountStateMachine directly)."""

    status: AccountStatus
    version: int = 1
    is_active: bool = False
    updated_at: datetime | None = None
    updated_by: str = "system"
    parent_account_id: object = None


# ============================================================================
# AccountStateMachine.can_transition / validate_transition
# ============================================================================


class TestCanTransition:
    def test_defined_transition_is_true(self):
        assert AccountStateMachine.can_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE) is True

    def test_undefined_transition_is_false(self):
        assert AccountStateMachine.can_transition(AccountStatus.DRAFT, AccountStatus.LOCKED) is False


class TestValidateTransition:
    def test_valid_transition_with_authorized_role(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.ACTIVE, user_role="finance_manager",
        )
        assert valid is True
        assert error is None

    def test_unauthorized_role_is_rejected(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.ACTIVE, user_role="user",
        )
        assert valid is False
        assert "requires one of roles" in error

    def test_super_admin_bypasses_role_check(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        valid, _error = AccountStateMachine.validate_transition(
            account, AccountStatus.ACTIVE, user_role="super_admin",
        )
        assert valid is True

    def test_terminal_state_rejects_any_transition(self):
        account = StubAccount(status=AccountStatus.CLOSED)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.ACTIVE, user_role="admin",
        )
        assert valid is False
        assert "terminal state" in error

    def test_terminal_state_to_same_state_still_checked_against_transition_map(self):
        # current_status == new_status short-circuits the terminal check,
        # but CLOSED->CLOSED is not itself in ALLOWED_TRANSITIONS.
        account = StubAccount(status=AccountStatus.CLOSED)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.CLOSED, user_role="admin",
        )
        assert valid is False
        assert "not allowed" in error

    def test_undefined_transition_rejected(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.LOCKED, user_role="admin",
        )
        assert valid is False
        assert "not allowed" in error

    def test_close_with_children_rejected(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.CLOSED, user_role="admin", has_children=True,
        )
        assert valid is False
        assert "child accounts" in error

    def test_close_with_balance_rejected_without_override(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.CLOSED, user_role="admin", has_balance=True,
        )
        assert valid is False
        assert "non-zero balance" in error

    def test_close_with_balance_allowed_with_override(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        valid, _error = AccountStateMachine.validate_transition(
            account, AccountStatus.CLOSED, user_role="admin", has_balance=True, override_reason="reconciled",
        )
        assert valid is True

    def test_close_with_transactions_rejected_without_override(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        valid, error = AccountStateMachine.validate_transition(
            account, AccountStatus.CLOSED, user_role="admin", has_transactions=True,
        )
        assert valid is False
        assert "transaction history" in error

    def test_account_with_is_active_flag_instead_of_status(self):
        class LegacyAccount:
            is_active = True

        valid, _error = AccountStateMachine.validate_transition(
            LegacyAccount(), AccountStatus.SUSPENDED, user_role="admin",
        )
        assert valid is True  # ACTIVE -> SUSPENDED is allowed for admin

    def test_account_with_neither_status_nor_is_active_rejected(self):
        class BareAccount:
            pass

        valid, error = AccountStateMachine.validate_transition(BareAccount(), AccountStatus.ACTIVE)
        assert valid is False
        assert "no status or is_active field" in error

    def test_real_account_entity_raises_due_to_incompatible_enum(self):
        """BUG-COA-SM-001: a real AccountEntity's `.status` is
        account_entity.AccountStatus, which has no `is_terminal()` method
        -- validate_transition() crashes instead of returning (False, msg)."""
        from domain.coa.account_code_vo import AccountCodeVO
        from domain.coa.account_entity import AccountEntity
        from domain.coa.account_normal_balance_vo import NormalBalance
        from domain.coa.account_type_enum import AccountType

        real_account = AccountEntity(
            id=uuid4(), legal_entity_id=uuid4(), code=AccountCodeVO("1000"), name="Cash",
            account_type=AccountType.ASSET, normal_balance=NormalBalance.DEBIT,
        )
        with pytest.raises(AttributeError, match="is_terminal"):
            AccountStateMachine.validate_transition(real_account, AccountStatus.ACTIVE, user_role="admin")


# ============================================================================
# AccountStateMachine.transition
# ============================================================================


class TestTransition:
    def test_transition_updates_status_and_version(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        updated = AccountStateMachine.transition(
            account, AccountStatus.ACTIVE, user_role="finance_manager", changed_by="user_a",
        )
        assert updated.status == AccountStatus.ACTIVE
        assert updated.version == 2
        assert updated.is_active is True
        assert updated.updated_by == "user_a"

    def test_transition_is_immutable_for_dataclass(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        updated = AccountStateMachine.transition(account, AccountStatus.ACTIVE, user_role="admin")
        assert account.status == AccountStatus.DRAFT  # original untouched
        assert updated is not account

    def test_transition_raises_on_invalid_transition(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        with pytest.raises(ValueError, match="Invalid state transition"):
            AccountStateMachine.transition(account, AccountStatus.LOCKED, user_role="admin")

    def test_transition_defaults_updated_by_to_user_role_when_not_given(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        updated = AccountStateMachine.transition(account, AccountStatus.ACTIVE, user_role="admin")
        assert updated.updated_by == "admin"


# ============================================================================
# AccountStateMachine — shortcut methods
# ============================================================================


class TestShortcutMethods:
    def test_can_activate(self):
        account = StubAccount(status=AccountStatus.DRAFT)
        assert AccountStateMachine.can_activate(account, user_role="admin") is True
        assert AccountStateMachine.can_activate(account, user_role="user") is False

    def test_can_suspend(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        assert AccountStateMachine.can_suspend(account, user_role="admin") is True

    def test_can_lock(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        assert AccountStateMachine.can_lock(account, user_role="auditor") is True
        assert AccountStateMachine.can_lock(account, user_role="user") is False

    def test_can_close(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        assert AccountStateMachine.can_close(account, user_role="admin") is True

    def test_can_close_with_balance_false_when_unset(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        assert AccountStateMachine.can_close(account, user_role="admin", has_balance=True) is False

    def test_can_archive(self):
        account = StubAccount(status=AccountStatus.ACTIVE)
        assert AccountStateMachine.can_archive(account, user_role="admin") is True


# ============================================================================
# get_allowed_next_states / get_allowed_transitions_with_roles
# ============================================================================


class TestAllowedTransitionsWithRoles:
    def test_get_allowed_next_states(self):
        result = set(AccountStateMachine.get_allowed_next_states(AccountStatus.ACTIVE))
        assert result == {AccountStatus.SUSPENDED, AccountStatus.LOCKED, AccountStatus.CLOSED, AccountStatus.ARCHIVED}

    def test_get_allowed_transitions_with_roles(self):
        details = AccountStateMachine.get_allowed_transitions_with_roles(AccountStatus.DRAFT)
        targets = {d["to"] for d in details}
        assert targets == {"active", "closed", "archived"}
        for d in details:
            assert "required_roles" in d
            assert "description" in d


# ============================================================================
# StatusTransitionRecord / TransitionHistory
# ============================================================================


class TestStatusTransitionRecord:
    def test_to_dict(self):
        record = StatusTransitionRecord(
            from_status=AccountStatus.DRAFT, to_status=AccountStatus.ACTIVE,
            transitioned_at=datetime.now(UTC), transitioned_by="user_a", reason="go live",
            user_role="admin",
        )
        d = record.to_dict()
        assert d["from_status"] == "draft"
        assert d["to_status"] == "active"
        assert d["reason"] == "go live"

    def test_from_dict_round_trip(self):
        record = StatusTransitionRecord(
            from_status=AccountStatus.DRAFT, to_status=AccountStatus.ACTIVE,
            transitioned_at=datetime.now(UTC), transitioned_by="user_a",
        )
        restored = StatusTransitionRecord.from_dict(record.to_dict())
        assert restored.from_status == AccountStatus.DRAFT
        assert restored.to_status == AccountStatus.ACTIVE
        assert restored.transitioned_by == "user_a"


class TestTransitionHistory:
    def test_add_and_get_history(self):
        history = TransitionHistory(account_id=uuid4())
        history.add_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE, "user_a")
        history.add_transition(AccountStatus.ACTIVE, AccountStatus.SUSPENDED, "user_b")
        records = history.get_history()
        assert len(records) == 2
        assert records[0].to_status == AccountStatus.ACTIVE

    def test_get_history_returns_copy(self):
        history = TransitionHistory(account_id=uuid4())
        history.add_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE, "user_a")
        records = history.get_history()
        records.append("fake")
        assert len(history.get_history()) == 1

    def test_get_last_transition(self):
        history = TransitionHistory(account_id=uuid4())
        history.add_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE, "user_a")
        history.add_transition(AccountStatus.ACTIVE, AccountStatus.SUSPENDED, "user_b")
        last = history.get_last_transition()
        assert last.to_status == AccountStatus.SUSPENDED

    def test_get_last_transition_empty_history_is_none(self):
        history = TransitionHistory(account_id=uuid4())
        assert history.get_last_transition() is None

    def test_clear(self):
        history = TransitionHistory(account_id=uuid4())
        history.add_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE, "user_a")
        history.clear()
        assert history.get_history() == []

    def test_to_dict(self):
        account_id = uuid4()
        history = TransitionHistory(account_id=account_id)
        history.add_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE, "user_a")
        d = history.to_dict()
        assert d["account_id"] == str(account_id)
        assert len(d["history"]) == 1


# ============================================================================
# COAStatus / COAStateMachine
# ============================================================================


class TestCOAStatus:
    def test_can_modify_only_active(self):
        assert COAStatus.ACTIVE.can_modify() is True
        assert COAStatus.LOCKED.can_modify() is False

    def test_can_read_active_and_locked(self):
        assert COAStatus.ACTIVE.can_read() is True
        assert COAStatus.LOCKED.can_read() is True
        assert COAStatus.ARCHIVED.can_read() is False


class TestCOAStateMachine:
    def test_can_transition_valid(self):
        assert COAStateMachine.can_transition(COAStatus.ACTIVE, COAStatus.LOCKED) is True

    def test_can_transition_invalid(self):
        assert COAStateMachine.can_transition(COAStatus.ARCHIVED, COAStatus.ACTIVE) is False

    def test_validate_transition_authorized(self):
        valid, _error = COAStateMachine.validate_transition(COAStatus.ACTIVE, COAStatus.LOCKED, user_role="admin")
        assert valid is True

    def test_validate_transition_unauthorized_role(self):
        valid, error = COAStateMachine.validate_transition(COAStatus.ACTIVE, COAStatus.ARCHIVED, user_role="auditor")
        assert valid is False
        assert "Required roles" in error

    def test_validate_transition_super_admin_bypass(self):
        valid, _error = COAStateMachine.validate_transition(COAStatus.ACTIVE, COAStatus.ARCHIVED, user_role="super_admin")
        assert valid is True

    def test_validate_transition_not_allowed(self):
        valid, error = COAStateMachine.validate_transition(COAStatus.ARCHIVED, COAStatus.ACTIVE, user_role="admin")
        assert valid is False
        assert "not allowed" in error

    def test_transition_success(self):
        @dataclass
        class StubCOA:
            status: COAStatus
            version: int = 1
            updated_at: datetime | None = None
            updated_by: str = "system"

        coa = StubCOA(status=COAStatus.ACTIVE)
        updated = COAStateMachine.transition(coa, COAStatus.LOCKED, user_role="admin", changed_by="user_a")
        assert updated.status == COAStatus.LOCKED
        assert updated.version == 2
        assert updated.updated_by == "user_a"

    def test_transition_raises_on_invalid(self):
        @dataclass
        class StubCOA:
            status: COAStatus
            version: int = 1
            updated_at: datetime | None = None
            updated_by: str = "system"

        coa = StubCOA(status=COAStatus.ARCHIVED)
        with pytest.raises(ValueError):
            COAStateMachine.transition(coa, COAStatus.ACTIVE, user_role="admin")


# ============================================================================
# Module-level helper functions
# ============================================================================


class TestModuleHelpers:
    def test_status_from_is_active(self):
        assert status_from_is_active(True) == AccountStatus.ACTIVE
        assert status_from_is_active(False) == AccountStatus.DRAFT

    def test_is_active_to_status_locked_takes_priority(self):
        assert is_active_to_status(True, is_locked=True) == AccountStatus.LOCKED

    def test_is_active_to_status_active(self):
        assert is_active_to_status(True, is_locked=False) == AccountStatus.ACTIVE

    def test_is_active_to_status_draft(self):
        assert is_active_to_status(False, is_locked=False) == AccountStatus.DRAFT

    def test_get_status_display_name_from_enum(self):
        assert get_status_display_name(AccountStatus.ACTIVE) == "Aktif"

    def test_get_status_display_name_from_valid_string(self):
        assert get_status_display_name("active") == "Aktif"

    def test_get_status_display_name_from_invalid_string_returns_none(self):
        # NOTE: despite the type hint suggesting a str is always returned,
        # an invalid string yields None here (from_string() returns None,
        # and that None is returned as-is instead of a fallback string).
        assert get_status_display_name("not_a_real_status") is None
