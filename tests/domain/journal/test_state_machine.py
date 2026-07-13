"""
Tests for domain/journal/state_machine.py

Covers:
- ALLOWED_TRANSITIONS graph sanity
- JournalStateMachine.can_transition / get_allowed_transitions / get_transition_rule
- validate_transition (balance / period-open / approval-role / reason / dual-control gates)
- get_status_flow, is_terminal, can_edit, can_delete, needs_approval, can_be_posted
- get_next_statuses / get_previous_statuses
- get_status_description, visualize
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.journal.journal_entity import JournalStatus
from domain.journal.state_machine import (
    ALLOWED_TRANSITIONS,
    TRANSITION_RULES,
    JournalStateMachine,
    StateTransitionRule,
)


# ============================================================================
# ALLOWED_TRANSITIONS graph
# ============================================================================


class TestAllowedTransitionsGraph:
    def test_all_statuses_have_an_entry(self):
        for status in JournalStatus:
            assert status in ALLOWED_TRANSITIONS

    def test_draft_can_go_to_submitted_archived_cancelled(self):
        assert ALLOWED_TRANSITIONS[JournalStatus.DRAFT] == {
            JournalStatus.SUBMITTED, JournalStatus.ARCHIVED, JournalStatus.CANCELLED,
        }

    def test_cancelled_is_terminal_in_graph(self):
        assert ALLOWED_TRANSITIONS[JournalStatus.CANCELLED] == set()

    def test_posted_can_only_go_to_reversed_or_archived(self):
        assert ALLOWED_TRANSITIONS[JournalStatus.POSTED] == {
            JournalStatus.REVERSED, JournalStatus.ARCHIVED,
        }


# ============================================================================
# can_transition / get_allowed_transitions / get_transition_rule
# ============================================================================


class TestCanTransition:
    def test_valid_transition_returns_true(self):
        assert JournalStateMachine.can_transition(JournalStatus.DRAFT, JournalStatus.SUBMITTED) is True

    def test_invalid_transition_returns_false(self):
        assert JournalStateMachine.can_transition(JournalStatus.DRAFT, JournalStatus.POSTED) is False

    def test_terminal_status_has_no_valid_transitions(self):
        assert JournalStateMachine.can_transition(JournalStatus.CANCELLED, JournalStatus.DRAFT) is False

    def test_get_allowed_transitions_matches_graph(self):
        result = set(JournalStateMachine.get_allowed_transitions(JournalStatus.SUBMITTED))
        assert result == {
            JournalStatus.APPROVED, JournalStatus.REJECTED,
            JournalStatus.DRAFT, JournalStatus.CANCELLED,
        }

    def test_get_allowed_transitions_empty_for_cancelled(self):
        assert JournalStateMachine.get_allowed_transitions(JournalStatus.CANCELLED) == []

    def test_get_transition_rule_found(self):
        rule = JournalStateMachine.get_transition_rule(JournalStatus.DRAFT, JournalStatus.SUBMITTED)
        assert rule is not None
        assert rule.check_balance is True

    def test_get_transition_rule_not_found_returns_none(self):
        rule = JournalStateMachine.get_transition_rule(JournalStatus.DRAFT, JournalStatus.POSTED)
        assert rule is None

    def test_transition_rules_list_is_exposed(self):
        assert isinstance(TRANSITION_RULES, list)
        assert all(isinstance(r, StateTransitionRule) for r in TRANSITION_RULES)


# ============================================================================
# validate_transition
# ============================================================================


class TestValidateTransition:
    def test_disallowed_graph_transition_is_invalid(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.DRAFT, JournalStatus.POSTED, user_role="poster",
        )
        assert valid is False
        assert "Cannot transition" in message

    def test_draft_to_submitted_requires_balance(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.DRAFT, JournalStatus.SUBMITTED, user_role="maker", is_balanced=False,
        )
        assert valid is False
        assert "balanced" in message

    def test_draft_to_submitted_succeeds_when_balanced(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.DRAFT, JournalStatus.SUBMITTED, user_role="maker", is_balanced=True,
        )
        assert valid is True
        assert message is None

    def test_approved_to_posted_requires_open_period(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.APPROVED, JournalStatus.POSTED, user_role="poster", period_is_open=False,
        )
        assert valid is False
        assert "period is closed" in message.lower()

    def test_approved_to_posted_succeeds_with_open_period(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.APPROVED, JournalStatus.POSTED, user_role="poster", period_is_open=True,
        )
        assert valid is True

    def test_submitted_to_approved_requires_approver_role(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.SUBMITTED, JournalStatus.APPROVED, user_role="maker",
        )
        assert valid is False
        assert "Approval required" in message

    def test_submitted_to_approved_succeeds_with_approver_role(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.SUBMITTED, JournalStatus.APPROVED, user_role="approver",
        )
        assert valid is True

    def test_submitted_to_approved_succeeds_with_manager_role(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.SUBMITTED, JournalStatus.APPROVED, user_role="manager",
        )
        assert valid is True

    def test_submitted_to_rejected_requires_reason(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.SUBMITTED, JournalStatus.REJECTED, user_role="approver", reason=None,
        )
        assert valid is False
        assert "Reason is required" in message

    def test_submitted_to_rejected_succeeds_with_reason(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.SUBMITTED, JournalStatus.REJECTED, user_role="approver", reason="not valid",
        )
        assert valid is True

    def test_posted_to_reversed_requires_manager_and_reason_and_open_period(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.POSTED, JournalStatus.REVERSED, user_role="manager",
            period_is_open=True, reason="correction",
        )
        assert valid is True

    def test_posted_to_reversed_fails_without_reason(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.POSTED, JournalStatus.REVERSED, user_role="manager",
            period_is_open=True, reason=None,
        )
        assert valid is False

    def test_dual_control_not_required_for_approve_to_post_by_default(self):
        # requires_dual_control=False on this rule, so large amounts should pass
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.APPROVED, JournalStatus.POSTED, user_role="poster",
            amount=Decimal("999999999999"),
        )
        assert valid is True

    def test_unknown_from_status_transition_is_invalid(self):
        valid, message = JournalStateMachine.validate_transition(
            JournalStatus.CANCELLED, JournalStatus.DRAFT, user_role="manager",
        )
        assert valid is False


# ============================================================================
# Status flow / terminal / editability helpers
# ============================================================================


class TestStatusHelpers:
    def test_get_status_flow_returns_all_statuses(self):
        flow = JournalStateMachine.get_status_flow()
        assert set(flow.keys()) == {s.value for s in JournalStatus}

    def test_get_status_flow_draft_values(self):
        flow = JournalStateMachine.get_status_flow()
        assert set(flow["draft"]) == {"submitted", "archived", "cancelled"}

    def test_is_terminal_true_for_cancelled(self):
        assert JournalStateMachine.is_terminal(JournalStatus.CANCELLED) is True

    def test_is_terminal_false_for_draft(self):
        assert JournalStateMachine.is_terminal(JournalStatus.DRAFT) is False

    @pytest.mark.parametrize(
        "status, expected",
        [
            (JournalStatus.DRAFT, True),
            (JournalStatus.REJECTED, True),
            (JournalStatus.SUBMITTED, False),
            (JournalStatus.POSTED, False),
        ],
    )
    def test_can_edit(self, status, expected):
        assert JournalStateMachine.can_edit(status) is expected

    def test_can_delete_only_draft(self):
        assert JournalStateMachine.can_delete(JournalStatus.DRAFT) is True
        assert JournalStateMachine.can_delete(JournalStatus.SUBMITTED) is False

    def test_needs_approval_only_submitted(self):
        assert JournalStateMachine.needs_approval(JournalStatus.SUBMITTED) is True
        assert JournalStateMachine.needs_approval(JournalStatus.DRAFT) is False

    def test_can_be_posted_only_approved(self):
        assert JournalStateMachine.can_be_posted(JournalStatus.APPROVED) is True
        assert JournalStateMachine.can_be_posted(JournalStatus.SUBMITTED) is False

    def test_get_next_statuses_matches_get_allowed_transitions(self):
        assert set(JournalStateMachine.get_next_statuses(JournalStatus.DRAFT)) == set(
            JournalStateMachine.get_allowed_transitions(JournalStatus.DRAFT)
        )

    def test_get_previous_statuses_of_posted(self):
        previous = set(JournalStateMachine.get_previous_statuses(JournalStatus.POSTED))
        assert previous == {JournalStatus.APPROVED, JournalStatus.ARCHIVED}

    def test_get_previous_statuses_of_draft(self):
        previous = set(JournalStateMachine.get_previous_statuses(JournalStatus.DRAFT))
        assert previous == {JournalStatus.SUBMITTED, JournalStatus.APPROVED, JournalStatus.REJECTED}

    def test_get_status_description_known_status(self):
        desc = JournalStateMachine.get_status_description(JournalStatus.POSTED)
        assert "Posted" in desc

    def test_get_status_description_all_statuses_have_descriptions(self):
        for status in JournalStatus:
            desc = JournalStateMachine.get_status_description(status)
            assert desc != "Unknown status"

    def test_visualize_returns_nonempty_string(self):
        text = JournalStateMachine.visualize()
        assert isinstance(text, str)
        assert "DRAFT" in text
        assert "POSTED" in text
