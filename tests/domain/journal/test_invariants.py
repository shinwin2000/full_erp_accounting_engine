"""
Tests for domain/journal/invariants.py

Covers:
- InvariantResult: add_error, merge, __bool__, __str__
- JournalInvariants: every static validation rule (balance, lines exist,
  line amounts, accounts exist, legal entity consistency, transaction date,
  journal number uniqueness, status transition, reversal reference,
  date consistency, currency consistency)
- JournalInvariantEnforcer: async enforce_create / enforce_status_transition /
  enforce_reversal, using mocked async collaborators
- JournalInvariantsValidator: thin wrapper methods + validate_all

KNOWN BUG (documented, not silently worked around):
  JournalInvariantsValidator.validate_all() and
  JournalInvariantEnforcer.enforce_create() both read `journal.posting_date`
  directly. JournalEntity (domain/journal/journal_entity.py) has NO
  `posting_date` field at all (only `transaction_date`), so calling these
  methods with a real JournalEntity instance raises AttributeError.
  test_validate_all_raises_attributeerror_due_to_missing_posting_date and
  test_enforce_create_raises_attributeerror_due_to_missing_posting_date pin
  down this actual (buggy) behavior. If `posting_date` is added to
  JournalEntity later, these two tests will start failing and must be
  revisited (that failure is exactly the useful signal).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from domain.journal.invariants import (
    InvariantResult,
    JournalInvariantEnforcer,
    JournalInvariants,
    JournalInvariantsValidator,
)
from domain.journal.journal_entity import JournalEntity, JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLineVO

# ============================================================================
# InvariantResult
# ============================================================================


class TestInvariantResult:
    def test_default_is_valid(self):
        result = InvariantResult()
        assert bool(result) is True
        assert result.errors == []

    def test_add_error_marks_invalid(self):
        result = InvariantResult()
        result.add_error("something wrong")
        assert result.is_valid is False
        assert "something wrong" in result.errors

    def test_merge_propagates_invalidity(self):
        result_a = InvariantResult(True)
        result_b = InvariantResult(False, ["b failed"])
        merged = result_a.merge(result_b)
        assert merged.is_valid is False
        assert "b failed" in merged.errors

    def test_merge_keeps_valid_when_both_valid(self):
        result_a = InvariantResult(True)
        result_b = InvariantResult(True)
        merged = result_a.merge(result_b)
        assert merged.is_valid is True

    def test_str_when_valid(self):
        assert str(InvariantResult(True)) == "InvariantResult: valid"

    def test_str_when_invalid(self):
        result = InvariantResult(False, ["e1", "e2"])
        assert str(result) == "InvariantResult: invalid - e1, e2"


# ============================================================================
# JournalInvariants — fixtures
# ============================================================================


@pytest.fixture
def legal_entity_id():
    return uuid4()


def make_lines(legal_entity_id, debit=Decimal("100"), credit=Decimal("100")):
    journal_id = uuid4()
    lines = []
    if debit > 0:
        lines.append(
            JournalLineVO.create_debit(journal_id, uuid4(), "1000", "Cash", debit, "debit", legal_entity_id)
        )
    if credit > 0:
        lines.append(
            JournalLineVO.create_credit(journal_id, uuid4(), "4000", "Revenue", credit, "credit", legal_entity_id)
        )
    return lines


# ============================================================================
# JournalInvariants — validate_balance
# ============================================================================


class TestValidateBalance:
    def test_balanced_is_valid(self):
        result = JournalInvariants.validate_balance(Decimal("100"), Decimal("100"))
        assert bool(result) is True

    def test_unbalanced_beyond_tolerance_is_invalid(self):
        result = JournalInvariants.validate_balance(Decimal("100"), Decimal("50"))
        assert bool(result) is False
        assert "not balanced" in result.errors[0]

    def test_within_tolerance_is_valid(self):
        result = JournalInvariants.validate_balance(
            Decimal("100.00005"), Decimal("100.00000"), tolerance=Decimal("0.0001")
        )
        assert bool(result) is True


# ============================================================================
# JournalInvariants — validate_lines_exist / validate_line_amounts
# ============================================================================


class TestValidateLinesExistAndAmounts:
    def test_empty_lines_is_invalid(self):
        result = JournalInvariants.validate_lines_exist([])
        assert bool(result) is False

    def test_nonempty_lines_is_valid(self, legal_entity_id):
        result = JournalInvariants.validate_lines_exist(make_lines(legal_entity_id))
        assert bool(result) is True

    def test_negative_or_zero_amount_lines_flagged(self, legal_entity_id):
        # JournalLineVO itself blocks amount<=0 at construction, so we simulate
        # a line-like object via SimpleNamespace to exercise the invariant directly.
        fake_line = SimpleNamespace(line_id=uuid4(), amount=Decimal("0"))
        result = JournalInvariants.validate_line_amounts([fake_line])
        assert bool(result) is False
        assert "invalid amount" in result.errors[0]

    def test_amount_exceeding_max_flagged(self):
        fake_line = SimpleNamespace(line_id=uuid4(), amount=Decimal("99999999999999"))
        result = JournalInvariants.validate_line_amounts([fake_line])
        assert bool(result) is False
        assert "exceeds maximum" in result.errors[0]

    def test_valid_amounts_pass(self, legal_entity_id):
        result = JournalInvariants.validate_line_amounts(make_lines(legal_entity_id))
        assert bool(result) is True


# ============================================================================
# JournalInvariants — validate_accounts_exist
# ============================================================================


class TestValidateAccountsExist:
    def test_missing_account_is_invalid(self, legal_entity_id):
        lines = make_lines(legal_entity_id)
        result = JournalInvariants.validate_accounts_exist(lines, account_getter=lambda account_id: None)
        assert bool(result) is False
        assert "not found" in result.errors[0]

    def test_inactive_account_is_invalid(self, legal_entity_id):
        lines = make_lines(legal_entity_id)
        inactive_account = SimpleNamespace(is_active=False)
        result = JournalInvariants.validate_accounts_exist(
            lines, account_getter=lambda account_id: inactive_account
        )
        assert bool(result) is False
        assert "not active" in result.errors[0]

    def test_active_account_is_valid(self, legal_entity_id):
        lines = make_lines(legal_entity_id)
        active_account = SimpleNamespace(is_active=True)
        result = JournalInvariants.validate_accounts_exist(
            lines, account_getter=lambda account_id: active_account
        )
        assert bool(result) is True

    def test_account_without_is_active_attr_defaults_active(self, legal_entity_id):
        lines = make_lines(legal_entity_id)
        account_no_flag = SimpleNamespace()
        result = JournalInvariants.validate_accounts_exist(
            lines, account_getter=lambda account_id: account_no_flag
        )
        assert bool(result) is True


# ============================================================================
# JournalInvariants — validate_legal_entity_consistency
# ============================================================================


class TestValidateLegalEntityConsistency:
    def test_matching_legal_entity_is_valid(self, legal_entity_id):
        lines = make_lines(legal_entity_id)
        result = JournalInvariants.validate_legal_entity_consistency(lines, legal_entity_id)
        assert bool(result) is True

    def test_mismatched_legal_entity_is_invalid(self, legal_entity_id):
        lines = make_lines(legal_entity_id)
        result = JournalInvariants.validate_legal_entity_consistency(lines, uuid4())
        assert bool(result) is False


# ============================================================================
# JournalInvariants — validate_transaction_date
# ============================================================================


class TestValidateTransactionDate:
    def test_future_date_is_invalid(self):
        future = datetime.now(UTC) + timedelta(days=5)
        result = JournalInvariants.validate_transaction_date(future)
        assert bool(result) is False
        assert "cannot be in the future" in result.errors[0]

    def test_recent_past_date_is_valid(self):
        recent = datetime.now(UTC) - timedelta(days=1)
        result = JournalInvariants.validate_transaction_date(recent)
        assert bool(result) is True

    def test_too_far_in_past_is_invalid(self):
        old = datetime.now(UTC) - timedelta(days=60)
        result = JournalInvariants.validate_transaction_date(old, max_backdate_days=30)
        assert bool(result) is False
        assert "exceeds limit" in result.errors[0]

    def test_before_period_start_is_invalid(self):
        now = datetime.now(UTC)
        period_start = now + timedelta(days=1)
        result = JournalInvariants.validate_transaction_date(now, period_start=period_start)
        assert bool(result) is False
        assert "before period start" in result.errors[0]

    def test_after_period_end_is_invalid(self):
        now = datetime.now(UTC)
        period_end = now - timedelta(days=1)
        result = JournalInvariants.validate_transaction_date(now, period_end=period_end)
        assert bool(result) is False
        assert "after period end" in result.errors[0]


# ============================================================================
# JournalInvariants — validate_journal_number_unique
# ============================================================================


class TestValidateJournalNumberUnique:
    def test_duplicate_number_is_invalid(self):
        result = JournalInvariants.validate_journal_number_unique("JRN-1", {"JRN-1", "JRN-2"})
        assert bool(result) is False
        assert "already exists" in result.errors[0]

    def test_unique_number_is_valid(self):
        result = JournalInvariants.validate_journal_number_unique("JRN-3", {"JRN-1", "JRN-2"})
        assert bool(result) is True

    def test_number_too_long_is_invalid(self):
        long_number = "J" * 51
        result = JournalInvariants.validate_journal_number_unique(long_number, set())
        assert bool(result) is False
        assert "exceeds maximum length" in result.errors[0]


# ============================================================================
# JournalInvariants — validate_status_transition
# ============================================================================


class TestValidateStatusTransition:
    def test_valid_transition_passes(self):
        result = JournalInvariants.validate_status_transition(
            JournalStatus.DRAFT, JournalStatus.SUBMITTED, user_role="maker", is_balanced=True,
        )
        assert bool(result) is True

    def test_invalid_transition_fails(self):
        result = JournalInvariants.validate_status_transition(
            JournalStatus.DRAFT, JournalStatus.POSTED, user_role="poster",
        )
        assert bool(result) is False


# ============================================================================
# JournalInvariants — validate_reversal_reference
# ============================================================================


class TestValidateReversalReference:
    def test_no_reversal_reference_is_valid(self):
        result = JournalInvariants.validate_reversal_reference(None)
        assert bool(result) is True

    def test_reversal_of_nonexistent_journal_is_invalid(self):
        result = JournalInvariants.validate_reversal_reference(uuid4(), original_journal_exists=False)
        assert bool(result) is False
        assert "not found" in result.errors[0]

    def test_reversal_of_unposted_journal_is_invalid(self):
        result = JournalInvariants.validate_reversal_reference(
            uuid4(), original_journal_exists=True, original_journal_is_posted=False,
        )
        assert bool(result) is False
        assert "not posted" in result.errors[0]

    def test_reversal_of_posted_journal_is_valid(self):
        result = JournalInvariants.validate_reversal_reference(
            uuid4(), original_journal_exists=True, original_journal_is_posted=True,
        )
        assert bool(result) is True


# ============================================================================
# JournalInvariants — validate_date_consistency
# ============================================================================


class TestValidateDateConsistency:
    def test_posting_date_before_transaction_date_is_invalid(self):
        transaction_date = datetime.now(UTC)
        posting_date = transaction_date - timedelta(days=1)
        result = JournalInvariants.validate_date_consistency(transaction_date, posting_date)
        assert bool(result) is False

    def test_posting_date_after_transaction_date_is_valid(self):
        transaction_date = datetime.now(UTC)
        posting_date = transaction_date + timedelta(hours=1)
        result = JournalInvariants.validate_date_consistency(transaction_date, posting_date)
        assert bool(result) is True

    def test_none_posting_date_is_valid(self):
        result = JournalInvariants.validate_date_consistency(datetime.now(UTC), None)
        assert bool(result) is True


# ============================================================================
# JournalInvariants — validate_currency_consistency
# ============================================================================


class TestValidateCurrencyConsistency:
    def test_empty_lines_is_valid(self):
        result = JournalInvariants.validate_currency_consistency([])
        assert bool(result) is True

    def test_consistent_currency_is_valid(self, legal_entity_id):
        result = JournalInvariants.validate_currency_consistency(make_lines(legal_entity_id))
        assert bool(result) is True

    def test_mismatched_currency_is_invalid(self, legal_entity_id):
        journal_id = uuid4()
        line_a = JournalLineVO.create_debit(
            journal_id, uuid4(), "1000", "Cash", Decimal("100"), "line a", legal_entity_id, currency="IDR"
        )
        line_b = JournalLineVO.create_credit(
            journal_id, uuid4(), "4000", "Rev", Decimal("100"), "line b", legal_entity_id, currency="USD"
        )
        result = JournalInvariants.validate_currency_consistency([line_a, line_b])
        assert bool(result) is False


# ============================================================================
# JournalInvariantEnforcer (async)
# ============================================================================


def make_entity(legal_entity_id, **overrides):
    now = datetime.now(UTC)
    defaults = dict(
        journal_id=uuid4(),
        journal_number="JRN-001",
        journal_type=JournalType.GENERAL,
        transaction_date=now,
        description="Test journal",
        legal_entity_id=legal_entity_id,
        status=JournalStatus.DRAFT,
        created_by="user_a",
        created_at=now,
        updated_at=now,
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
    )
    defaults.update(overrides)
    return JournalEntity(**defaults)


@pytest.fixture
def enforcer(legal_entity_id):
    async def account_getter(account_id):
        return SimpleNamespace(is_active=True)

    async def journal_number_checker(entity_legal_entity_id):
        return set()

    async def period_checker(entity_legal_entity_id, transaction_date):
        return (None, None)

    # account_getter must be sync per the type hint usage in validate_accounts_exist
    # (it is called directly, not awaited) -- confirm with a sync callable instead.
    def sync_account_getter(account_id):
        return SimpleNamespace(is_active=True)

    return JournalInvariantEnforcer(
        account_getter=sync_account_getter,
        journal_number_checker=journal_number_checker,
        period_checker=period_checker,
    )


class TestJournalInvariantEnforcer:
    async def test_enforce_create_raises_attributeerror_due_to_missing_posting_date(
        self, enforcer, legal_entity_id
    ):
        """
        KNOWN BUG: enforce_create() reads `journal.posting_date`, but
        JournalEntity has no such field. This currently raises AttributeError
        for any real JournalEntity, so enforce_create() cannot be used
        end-to-end until the source is fixed.
        """
        entity = make_entity(legal_entity_id)
        lines = make_lines(legal_entity_id)
        with pytest.raises(AttributeError, match="posting_date"):
            await enforcer.enforce_create(entity, lines)

    async def test_enforce_status_transition_valid(self, enforcer, legal_entity_id):
        entity = make_entity(legal_entity_id, status=JournalStatus.DRAFT)
        result = await enforcer.enforce_status_transition(
            entity, JournalStatus.SUBMITTED, user_role="maker", is_balanced=True,
        )
        assert bool(result) is True

    async def test_enforce_status_transition_invalid(self, enforcer, legal_entity_id):
        entity = make_entity(legal_entity_id, status=JournalStatus.DRAFT)
        result = await enforcer.enforce_status_transition(
            entity, JournalStatus.POSTED, user_role="poster",
        )
        assert bool(result) is False

    async def test_enforce_reversal_valid(self, enforcer):
        result = await enforcer.enforce_reversal(uuid4(), original_exists=True, original_posted=True)
        assert bool(result) is True

    async def test_enforce_reversal_invalid_when_not_posted(self, enforcer):
        result = await enforcer.enforce_reversal(uuid4(), original_exists=True, original_posted=False)
        assert bool(result) is False


# ============================================================================
# JournalInvariantsValidator
# ============================================================================


class TestJournalInvariantsValidator:
    @pytest.fixture
    def validator(self):
        return JournalInvariantsValidator()

    def test_validate_balance_delegates(self, validator):
        result = validator.validate_balance(Decimal("100"), Decimal("100"))
        assert bool(result) is True

    def test_validate_lines_exist_delegates(self, validator):
        assert bool(validator.validate_lines_exist([])) is False

    def test_validate_line_amounts_delegates(self, validator, legal_entity_id):
        assert bool(validator.validate_line_amounts(make_lines(legal_entity_id))) is True

    def test_validate_legal_entity_consistency_delegates(self, validator, legal_entity_id):
        lines = make_lines(legal_entity_id)
        assert bool(validator.validate_legal_entity_consistency(lines, legal_entity_id)) is True

    def test_validate_transaction_date_delegates(self, validator):
        result = validator.validate_transaction_date(datetime.now(UTC) - timedelta(days=1))
        assert bool(result) is True

    def test_validate_accounts_exist_delegates(self, validator, legal_entity_id):
        lines = make_lines(legal_entity_id)
        result = validator.validate_accounts_exist(lines, account_getter=lambda a: None)
        assert bool(result) is False

    def test_validate_journal_number_unique_delegates(self, validator):
        assert bool(validator.validate_journal_number_unique("X", set())) is True

    def test_validate_status_transition_delegates(self, validator):
        result = validator.validate_status_transition(
            JournalStatus.DRAFT, JournalStatus.SUBMITTED, "maker"
        )
        assert bool(result) is True

    def test_validate_reversal_reference_delegates(self, validator):
        assert bool(validator.validate_reversal_reference(None)) is True

    def test_validate_currency_consistency_delegates(self, validator, legal_entity_id):
        assert bool(validator.validate_currency_consistency(make_lines(legal_entity_id))) is True

    def test_validate_date_consistency_delegates(self, validator):
        now = datetime.now(UTC)
        assert bool(validator.validate_date_consistency(now, now + timedelta(hours=1))) is True

    def test_validate_all_raises_attributeerror_due_to_missing_posting_date(
        self, validator, legal_entity_id
    ):
        """
        KNOWN BUG: validate_all() unconditionally accesses `journal.posting_date`
        via `self.validate_date_consistency(journal.transaction_date, journal.posting_date)`.
        JournalEntity has no `posting_date` attribute, so this always raises
        AttributeError for a real JournalEntity today. This test pins down
        that current (broken) behavior; if `posting_date` is added to
        JournalEntity, this test will need to be updated to assert success
        instead.
        """
        entity = make_entity(legal_entity_id)
        lines = make_lines(legal_entity_id)
        with pytest.raises(AttributeError, match="posting_date"):
            validator.validate_all(entity, lines)
