# tests/domain/journal/test_invariants.py
"""
Comprehensive unit tests for invariants.py.
Covers all public methods with strong assertions using mocks where needed.
All datetime usage is mocked to avoid flakiness.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.coa.account_entity import AccountEntity
from domain.journal.invariants import (
    InvariantResult,
    JournalInvariantEnforcer,
    JournalInvariants,
    JournalInvariantsValidator,
)
from domain.journal.journal_entity import JournalEntity, JournalStatus
from domain.journal.journal_line_vo import JournalLineVO, JournalSide
from domain.journal.state_machine import JournalStateMachine

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_FUTURE = FIXED_NOW + timedelta(days=5)
FIXED_PAST = FIXED_NOW - timedelta(days=5)
FIXED_OLD_PAST = FIXED_NOW - timedelta(days=60)
FIXED_PERIOD_START = FIXED_NOW - timedelta(days=10)
FIXED_PERIOD_END = FIXED_NOW + timedelta(days=10)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in invariants module to fixed time."""
    with patch("domain.journal.invariants.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Helper functions and fixtures
# ============================================================================

def create_line(
    amount: Decimal = Decimal("1000"),
    side: JournalSide = JournalSide.DEBIT,
    legal_entity_id: UUID | None = None,
    currency: str = "IDR",
    account_id: UUID | None = None,
    account_code: str = "1000",
) -> JournalLineVO:
    if legal_entity_id is None:
        legal_entity_id = uuid4()
    if account_id is None:
        account_id = uuid4()
    return JournalLineVO(
        line_id=uuid4(),
        journal_id=uuid4(),
        account_id=account_id,
        account_code=account_code,
        account_name="Test Account",
        side=side,
        amount=amount,
        description="Test line",
        legal_entity_id=legal_entity_id,
        currency=currency,
    )


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def sample_lines(legal_entity_id):
    return [
        create_line(amount=Decimal("1000"), side=JournalSide.DEBIT, legal_entity_id=legal_entity_id),
        create_line(amount=Decimal("1000"), side=JournalSide.CREDIT, legal_entity_id=legal_entity_id),
    ]


@pytest.fixture
def sample_journal(legal_entity_id):
    return JournalEntity(
        journal_id=uuid4(),
        journal_number="JRN-001",
        legal_entity_id=legal_entity_id,
        transaction_date=FIXED_NOW,
        posting_date=FIXED_NOW,
        status=JournalStatus.DRAFT,
        description="Test journal",
        created_by="system",
    )


@pytest.fixture
def account_getter():
    def getter(account_id: UUID) -> AccountEntity | None:
        account = MagicMock(spec=AccountEntity)
        account.is_active = True
        account.account_code = "1000"
        return account
    return getter


@pytest.fixture
def account_getter_inactive():
    def getter(account_id: UUID) -> AccountEntity | None:
        account = MagicMock(spec=AccountEntity)
        account.is_active = False
        account.account_code = "1000"
        return account
    return getter


@pytest.fixture
def account_getter_not_found():
    def getter(account_id: UUID) -> AccountEntity | None:
        return None
    return getter


@pytest.fixture
def journal_number_checker():
    async def checker(legal_entity_id: UUID) -> set[str]:
        return {"JRN-001", "JRN-002"}
    return checker


@pytest.fixture
def period_checker():
    async def checker(legal_entity_id: UUID, tx_date: datetime) -> tuple[datetime | None, datetime | None]:
        return FIXED_PERIOD_START, FIXED_PERIOD_END
    return checker


# ============================================================================
# Test InvariantResult
# ============================================================================

class TestInvariantResult:
    def test_construction(self):
        result = InvariantResult(is_valid=True, errors=[])
        assert result.is_valid is True
        assert result.errors == []

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("error 1")
        assert result.is_valid is False
        assert result.errors == ["error 1"]

    def test_merge(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["e1", "e2"])
        r1.merge(r2)
        assert r1.is_valid is False
        assert r1.errors == ["e1", "e2"]

    def test_bool(self):
        result = InvariantResult()
        assert bool(result) is True
        result.add_error("err")
        assert bool(result) is False

    def test_str(self):
        result = InvariantResult()
        assert str(result) == "InvariantResult: valid"
        result.add_error("error")
        assert "invalid" in str(result)


# ============================================================================
# Test JournalInvariants (static methods)
# ============================================================================

class TestJournalInvariants:
    def test_validate_balance_balanced(self):
        result = JournalInvariants.validate_balance(Decimal("1000"), Decimal("1000"))
        assert result.is_valid is True

    def test_validate_balance_unbalanced(self):
        result = JournalInvariants.validate_balance(Decimal("1000"), Decimal("999"))
        assert result.is_valid is False
        assert "not balanced" in result.errors[0]

    def test_validate_balance_negative_tolerance(self):
        result = JournalInvariants.validate_balance(
            Decimal("1000"), Decimal("999.9995"), tolerance=Decimal("0.001")
        )
        assert result.is_valid is True

    def test_validate_lines_exist_valid(self):
        lines = [MagicMock()]
        result = JournalInvariants.validate_lines_exist(lines)
        assert result.is_valid is True

    def test_validate_lines_exist_empty(self):
        result = JournalInvariants.validate_lines_exist([])
        assert result.is_valid is False
        assert "at least one line" in result.errors[0]

    def test_validate_line_amounts_valid(self):
        line = MagicMock()
        line.amount = Decimal("100")
        line.line_id = uuid4()
        result = JournalInvariants.validate_line_amounts([line])
        assert result.is_valid is True

    def test_validate_line_amounts_negative(self):
        line = MagicMock()
        line.amount = Decimal("-100")
        line.line_id = uuid4()
        result = JournalInvariants.validate_line_amounts([line])
        assert result.is_valid is False
        assert "invalid amount" in result.errors[0]

    def test_validate_line_amounts_too_high(self):
        line = MagicMock()
        line.amount = Decimal("99999999999999")
        line.line_id = uuid4()
        result = JournalInvariants.validate_line_amounts([line])
        assert result.is_valid is False
        assert "exceeds maximum" in result.errors[0]

    def test_validate_line_amounts_zero(self):
        line = MagicMock()
        line.amount = Decimal("0")
        line.line_id = uuid4()
        result = JournalInvariants.validate_line_amounts([line])
        assert result.is_valid is False
        assert "invalid amount" in result.errors[0]

    def test_validate_accounts_exist_valid(self, account_getter):
        line = MagicMock()
        line.account_id = uuid4()
        line.account_code = "1000"
        result = JournalInvariants.validate_accounts_exist([line], account_getter)
        assert result.is_valid is True

    def test_validate_accounts_exist_not_found(self, account_getter_not_found):
        line = MagicMock()
        line.account_id = uuid4()
        line.account_code = "1000"
        result = JournalInvariants.validate_accounts_exist([line], account_getter_not_found)
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    def test_validate_accounts_exist_inactive(self, account_getter_inactive):
        line = MagicMock()
        line.account_id = uuid4()
        line.account_code = "1000"
        result = JournalInvariants.validate_accounts_exist([line], account_getter_inactive)
        assert result.is_valid is False
        assert "not active" in result.errors[0]

    def test_validate_legal_entity_consistency_valid(self, sample_lines, legal_entity_id):
        result = JournalInvariants.validate_legal_entity_consistency(sample_lines, legal_entity_id)
        assert result.is_valid is True

    def test_validate_legal_entity_consistency_invalid(self, sample_lines):
        other_id = uuid4()
        result = JournalInvariants.validate_legal_entity_consistency(sample_lines, other_id)
        assert result.is_valid is False
        assert "legal_entity_id" in result.errors[0]

    def test_validate_transaction_date_valid(self):
        result = JournalInvariants.validate_transaction_date(FIXED_PAST)
        assert result.is_valid is True

    def test_validate_transaction_date_future(self):
        result = JournalInvariants.validate_transaction_date(FIXED_FUTURE)
        assert result.is_valid is False
        assert "cannot be in the future" in result.errors[0]

    def test_validate_transaction_date_backdate_exceeds(self):
        result = JournalInvariants.validate_transaction_date(FIXED_OLD_PAST, max_backdate_days=30)
        assert result.is_valid is False
        assert "exceeds limit" in result.errors[0]

    def test_validate_transaction_date_with_period_valid(self):
        result = JournalInvariants.validate_transaction_date(
            FIXED_NOW, period_start=FIXED_PERIOD_START, period_end=FIXED_PERIOD_END
        )
        assert result.is_valid is True

    def test_validate_transaction_date_before_period(self):
        result = JournalInvariants.validate_transaction_date(
            FIXED_PERIOD_START - timedelta(days=1),
            period_start=FIXED_PERIOD_START,
            period_end=FIXED_PERIOD_END
        )
        assert result.is_valid is False
        assert "before period start" in result.errors[0]

    def test_validate_transaction_date_after_period(self):
        result = JournalInvariants.validate_transaction_date(
            FIXED_PERIOD_END + timedelta(days=1),
            period_start=FIXED_PERIOD_START,
            period_end=FIXED_PERIOD_END
        )
        assert result.is_valid is False
        assert "after period end" in result.errors[0]

    def test_validate_journal_number_unique_valid(self):
        existing = {"JRN-001", "JRN-002"}
        result = JournalInvariants.validate_journal_number_unique("JRN-003", existing)
        assert result.is_valid is True

    def test_validate_journal_number_unique_duplicate(self):
        existing = {"JRN-001", "JRN-002"}
        result = JournalInvariants.validate_journal_number_unique("JRN-001", existing)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_journal_number_unique_too_long(self):
        long_number = "J" * 60
        result = JournalInvariants.validate_journal_number_unique(long_number, set())
        assert result.is_valid is False
        assert "exceeds maximum length" in result.errors[0]

    def test_validate_journal_number_unique_empty(self):
        result = JournalInvariants.validate_journal_number_unique("", set())
        # Empty string is not duplicate, but we check length? Actually len("") is 0, no error for length.
        # But the method doesn't validate non-empty, so we need to check that it passes.
        # However, empty string would cause validation errors elsewhere, but here it passes.
        assert result.is_valid is True

    @patch("domain.journal.invariants.JournalStateMachine.validate_transition")
    def test_validate_status_transition_valid(self, mock_validate):
        mock_validate.return_value = (True, None)
        result = JournalInvariants.validate_status_transition(
            current_status=JournalStatus.DRAFT,
            new_status=JournalStatus.SUBMITTED,
            user_role="accountant",
            is_balanced=True,
            period_is_open=True,
        )
        assert result.is_valid is True
        mock_validate.assert_called_once()

    @patch("domain.journal.invariants.JournalStateMachine.validate_transition")
    def test_validate_status_transition_invalid(self, mock_validate):
        mock_validate.return_value = (False, "Invalid transition")
        result = JournalInvariants.validate_status_transition(
            current_status=JournalStatus.DRAFT,
            new_status=JournalStatus.POSTED,
            user_role="accountant",
            is_balanced=True,
            period_is_open=True,
        )
        assert result.is_valid is False
        assert "Invalid transition" in result.errors[0]

    def test_validate_reversal_reference_none(self):
        result = JournalInvariants.validate_reversal_reference(None)
        assert result.is_valid is True

    def test_validate_reversal_reference_valid(self):
        original_id = uuid4()
        result = JournalInvariants.validate_reversal_reference(
            reversal_of=original_id,
            original_journal_exists=True,
            original_journal_is_posted=True,
        )
        assert result.is_valid is True

    def test_validate_reversal_reference_not_exists(self):
        original_id = uuid4()
        result = JournalInvariants.validate_reversal_reference(
            reversal_of=original_id,
            original_journal_exists=False,
            original_journal_is_posted=True,
        )
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    def test_validate_reversal_reference_not_posted(self):
        original_id = uuid4()
        result = JournalInvariants.validate_reversal_reference(
            reversal_of=original_id,
            original_journal_exists=True,
            original_journal_is_posted=False,
        )
        assert result.is_valid is False
        assert "not posted" in result.errors[0]

    def test_validate_date_consistency_valid(self):
        tx_date = FIXED_NOW
        posting_date = tx_date + timedelta(days=1)
        result = JournalInvariants.validate_date_consistency(tx_date, posting_date)
        assert result.is_valid is True

    def test_validate_date_consistency_posting_before_transaction(self):
        tx_date = FIXED_NOW
        posting_date = tx_date - timedelta(days=1)
        result = JournalInvariants.validate_date_consistency(tx_date, posting_date)
        assert result.is_valid is False
        assert "cannot be before transaction date" in result.errors[0]

    def test_validate_date_consistency_posting_none(self):
        tx_date = FIXED_NOW
        result = JournalInvariants.validate_date_consistency(tx_date, None)
        assert result.is_valid is True

    def test_validate_currency_consistency_valid(self, sample_lines):
        result = JournalInvariants.validate_currency_consistency(sample_lines)
        assert result.is_valid is True

    def test_validate_currency_consistency_invalid(self, sample_lines):
        # Modify one line to have different currency
        line = sample_lines[0]
        invalid_line = JournalLineVO(
            line_id=line.line_id,
            journal_id=line.journal_id,
            account_id=line.account_id,
            account_code=line.account_code,
            account_name=line.account_name,
            side=line.side,
            amount=line.amount,
            description=line.description,
            legal_entity_id=line.legal_entity_id,
            currency="USD",
        )
        lines = [invalid_line, sample_lines[1]]
        result = JournalInvariants.validate_currency_consistency(lines)
        assert result.is_valid is False
        assert "currency" in result.errors[0]

    def test_validate_currency_consistency_empty(self):
        result = JournalInvariants.validate_currency_consistency([])
        assert result.is_valid is True


# ============================================================================
# Test JournalInvariantEnforcer
# ============================================================================

@pytest.mark.asyncio
class TestJournalInvariantEnforcer:
    async def test_enforce_create_valid(self, sample_journal, sample_lines, account_getter,
                                        journal_number_checker, period_checker):
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, sample_lines)
        assert result.is_valid is True

    async def test_enforce_create_invalid_balance(self, sample_journal, account_getter,
                                                  journal_number_checker, period_checker):
        le_id = sample_journal.legal_entity_id
        lines = [
            create_line(amount=Decimal("1000"), side=JournalSide.DEBIT, legal_entity_id=le_id),
            create_line(amount=Decimal("999"), side=JournalSide.CREDIT, legal_entity_id=le_id),
        ]
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, lines)
        assert result.is_valid is False
        assert "not balanced" in result.errors[0]

    async def test_enforce_create_empty_lines(self, sample_journal, account_getter,
                                              journal_number_checker, period_checker):
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, [])
        assert result.is_valid is False
        assert "at least one line" in result.errors[0]

    async def test_enforce_create_duplicate_number(self, sample_journal, sample_lines,
                                                   account_getter, journal_number_checker, period_checker):
        sample_journal.journal_number = "JRN-001"
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, sample_lines)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_create_inactive_account(self, sample_journal, sample_lines,
                                                   account_getter_inactive, journal_number_checker, period_checker):
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter_inactive,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, sample_lines)
        assert result.is_valid is False
        assert "not active" in result.errors[0]

    async def test_enforce_create_account_not_found(self, sample_journal, sample_lines,
                                                    account_getter_not_found, journal_number_checker, period_checker):
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter_not_found,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, sample_lines)
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    async def test_enforce_create_currency_mismatch(self, sample_journal, sample_lines,
                                                    account_getter, journal_number_checker, period_checker):
        # Create lines with different currencies
        le_id = sample_journal.legal_entity_id
        lines = [
            create_line(amount=Decimal("1000"), side=JournalSide.DEBIT, legal_entity_id=le_id, currency="IDR"),
            create_line(amount=Decimal("1000"), side=JournalSide.CREDIT, legal_entity_id=le_id, currency="USD"),
        ]
        enforcer = JournalInvariantEnforcer(
            account_getter=account_getter,
            journal_number_checker=journal_number_checker,
            period_checker=period_checker,
        )
        result = await enforcer.enforce_create(sample_journal, lines)
        assert result.is_valid is False
        assert "currency" in result.errors[0]

    async def test_enforce_status_transition(self, sample_journal):
        enforcer = JournalInvariantEnforcer(
            account_getter=MagicMock(),
            journal_number_checker=MagicMock(),
            period_checker=MagicMock(),
        )
        with patch("domain.journal.invariants.JournalStateMachine.validate_transition") as mock_validate:
            mock_validate.return_value = (True, None)
            result = await enforcer.enforce_status_transition(
                journal=sample_journal,
                new_status=JournalStatus.SUBMITTED,
                user_role="accountant",
                is_balanced=True,
                period_is_open=True,
            )
            assert result.is_valid is True

    async def test_enforce_status_transition_invalid(self, sample_journal):
        enforcer = JournalInvariantEnforcer(
            account_getter=MagicMock(),
            journal_number_checker=MagicMock(),
            period_checker=MagicMock(),
        )
        with patch("domain.journal.invariants.JournalStateMachine.validate_transition") as mock_validate:
            mock_validate.return_value = (False, "Invalid")
            result = await enforcer.enforce_status_transition(
                journal=sample_journal,
                new_status=JournalStatus.POSTED,
                user_role="accountant",
                is_balanced=True,
                period_is_open=True,
            )
            assert result.is_valid is False
            assert "Invalid" in result.errors[0]

    async def test_enforce_reversal_valid(self):
        enforcer = JournalInvariantEnforcer(
            account_getter=MagicMock(),
            journal_number_checker=MagicMock(),
            period_checker=MagicMock(),
        )
        original_id = uuid4()
        result = await enforcer.enforce_reversal(
            reversal_of=original_id,
            original_exists=True,
            original_posted=True,
        )
        assert result.is_valid is True

    async def test_enforce_reversal_not_exists(self):
        enforcer = JournalInvariantEnforcer(
            account_getter=MagicMock(),
            journal_number_checker=MagicMock(),
            period_checker=MagicMock(),
        )
        original_id = uuid4()
        result = await enforcer.enforce_reversal(
            reversal_of=original_id,
            original_exists=False,
            original_posted=True,
        )
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    async def test_enforce_reversal_not_posted(self):
        enforcer = JournalInvariantEnforcer(
            account_getter=MagicMock(),
            journal_number_checker=MagicMock(),
            period_checker=MagicMock(),
        )
        original_id = uuid4()
        result = await enforcer.enforce_reversal(
            reversal_of=original_id,
            original_exists=True,
            original_posted=False,
        )
        assert result.is_valid is False
        assert "not posted" in result.errors[0]


# ============================================================================
# Test JournalInvariantsValidator
# ============================================================================

class TestJournalInvariantsValidator:
    def test_validate_balance(self):
        validator = JournalInvariantsValidator()
        result = validator.validate_balance(Decimal("1000"), Decimal("1000"))
        assert result.is_valid is True
        result2 = validator.validate_balance(Decimal("1000"), Decimal("999"))
        assert result2.is_valid is False

    def test_validate_lines_exist(self):
        validator = JournalInvariantsValidator()
        result = validator.validate_lines_exist([MagicMock()])
        assert result.is_valid is True
        result2 = validator.validate_lines_exist([])
        assert result2.is_valid is False

    def test_validate_line_amounts(self):
        validator = JournalInvariantsValidator()
        line = MagicMock()
        line.amount = Decimal("100")
        line.line_id = uuid4()
        result = validator.validate_line_amounts([line])
        assert result.is_valid is True
        line2 = MagicMock()
        line2.amount = Decimal("-100")
        line2.line_id = uuid4()
        result2 = validator.validate_line_amounts([line2])
        assert result2.is_valid is False

    def test_validate_legal_entity_consistency(self, sample_lines):
        validator = JournalInvariantsValidator()
        le_id = sample_lines[0].legal_entity_id
        result = validator.validate_legal_entity_consistency(sample_lines, le_id)
        assert result.is_valid is True
        other_id = uuid4()
        result2 = validator.validate_legal_entity_consistency(sample_lines, other_id)
        assert result2.is_valid is False

    def test_validate_transaction_date(self):
        validator = JournalInvariantsValidator()
        result = validator.validate_transaction_date(FIXED_PAST)
        assert result.is_valid is True
        result2 = validator.validate_transaction_date(FIXED_FUTURE)
        assert result2.is_valid is False
        result3 = validator.validate_transaction_date(FIXED_OLD_PAST, max_backdate_days=30)
        assert result3.is_valid is False

    def test_validate_transaction_date_with_period(self):
        validator = JournalInvariantsValidator()
        result = validator.validate_transaction_date(
            FIXED_NOW,
            period_start=FIXED_PERIOD_START,
            period_end=FIXED_PERIOD_END
        )
        assert result.is_valid is True
        # Before period
        result2 = validator.validate_transaction_date(
            FIXED_PERIOD_START - timedelta(days=1),
            period_start=FIXED_PERIOD_START,
            period_end=FIXED_PERIOD_END
        )
        assert result2.is_valid is False
        # After period
        result3 = validator.validate_transaction_date(
            FIXED_PERIOD_END + timedelta(days=1),
            period_start=FIXED_PERIOD_START,
            period_end=FIXED_PERIOD_END
        )
        assert result3.is_valid is False

    def test_validate_accounts_exist(self, account_getter):
        validator = JournalInvariantsValidator()
        line = MagicMock()
        line.account_id = uuid4()
        result = validator.validate_accounts_exist([line], account_getter)
        assert result.is_valid is True

    def test_validate_accounts_exist_not_found(self, account_getter_not_found):
        validator = JournalInvariantsValidator()
        line = MagicMock()
        line.account_id = uuid4()
        result = validator.validate_accounts_exist([line], account_getter_not_found)
        assert result.is_valid is False

    def test_validate_accounts_exist_inactive(self, account_getter_inactive):
        validator = JournalInvariantsValidator()
        line = MagicMock()
        line.account_id = uuid4()
        result = validator.validate_accounts_exist([line], account_getter_inactive)
        assert result.is_valid is False

    def test_validate_journal_number_unique(self):
        validator = JournalInvariantsValidator()
        existing = {"JRN-001", "JRN-002"}
        result = validator.validate_journal_number_unique("JRN-003", existing)
        assert result.is_valid is True
        result2 = validator.validate_journal_number_unique("JRN-001", existing)
        assert result2.is_valid is False
        long_number = "J" * 60
        result3 = validator.validate_journal_number_unique(long_number, set())
        assert result3.is_valid is False

    @patch("domain.journal.invariants.JournalStateMachine.validate_transition")
    def test_validate_status_transition(self, mock_validate):
        validator = JournalInvariantsValidator()
        mock_validate.return_value = (True, None)
        result = validator.validate_status_transition(
            current_status=JournalStatus.DRAFT,
            new_status=JournalStatus.SUBMITTED,
            user_role="accountant",
        )
        assert result.is_valid is True
        mock_validate.return_value = (False, "Invalid")
        result2 = validator.validate_status_transition(
            current_status=JournalStatus.DRAFT,
            new_status=JournalStatus.POSTED,
            user_role="accountant",
        )
        assert result2.is_valid is False

    def test_validate_reversal_reference(self):
        validator = JournalInvariantsValidator()
        original_id = uuid4()
        result = validator.validate_reversal_reference(original_id, original_journal_exists=True)
        assert result.is_valid is True
        result2 = validator.validate_reversal_reference(original_id, original_journal_exists=False)
        assert result2.is_valid is False
        result3 = validator.validate_reversal_reference(None)
        assert result3.is_valid is True

    def test_validate_currency_consistency(self, sample_lines):
        validator = JournalInvariantsValidator()
        result = validator.validate_currency_consistency(sample_lines)
        assert result.is_valid is True

    def test_validate_currency_consistency_invalid(self, sample_lines):
        validator = JournalInvariantsValidator()
        invalid_line = JournalLineVO(
            line_id=uuid4(),
            journal_id=uuid4(),
            account_id=uuid4(),
            account_code="1000",
            account_name="Cash",
            side=JournalSide.DEBIT,
            amount=Decimal("100"),
            description="Test",
            legal_entity_id=sample_lines[0].legal_entity_id,
            currency="USD",
        )
        lines = [invalid_line, sample_lines[1]]
        result = validator.validate_currency_consistency(lines)
        assert result.is_valid is False
        result2 = validator.validate_currency_consistency([])
        assert result2.is_valid is True

    def test_validate_date_consistency(self):
        validator = JournalInvariantsValidator()
        tx_date = FIXED_NOW
        posting_date = tx_date + timedelta(days=1)
        result = validator.validate_date_consistency(tx_date, posting_date)
        assert result.is_valid is True
        posting_date2 = tx_date - timedelta(days=1)
        result2 = validator.validate_date_consistency(tx_date, posting_date2)
        assert result2.is_valid is False
        result3 = validator.validate_date_consistency(tx_date, None)
        assert result3.is_valid is True

    def test_validate_all_valid(self, sample_journal, sample_lines):
        validator = JournalInvariantsValidator()
        with patch("domain.journal.invariants.JournalStateMachine.validate_transition") as mock_validate:
            mock_validate.return_value = (True, None)
            result = validator.validate_all(sample_journal, sample_lines)
            assert result.is_valid is True

    def test_validate_all_invalid_balance(self, sample_journal):
        validator = JournalInvariantsValidator()
        le_id = sample_journal.legal_entity_id
        lines = [
            create_line(amount=Decimal("1000"), side=JournalSide.DEBIT, legal_entity_id=le_id),
            create_line(amount=Decimal("999"), side=JournalSide.CREDIT, legal_entity_id=le_id),
        ]
        result = validator.validate_all(sample_journal, lines)
        assert result.is_valid is False
        assert "not balanced" in result.errors[0]

    def test_validate_all_invalid_legal_entity(self, sample_journal):
        validator = JournalInvariantsValidator()
        other_id = uuid4()
        lines = [
            create_line(amount=Decimal("1000"), side=JournalSide.DEBIT, legal_entity_id=other_id),
            create_line(amount=Decimal("1000"), side=JournalSide.CREDIT, legal_entity_id=other_id),
        ]
        result = validator.validate_all(sample_journal, lines)
        assert result.is_valid is False
        assert "legal_entity_id" in result.errors[0]

    def test_validate_all_empty_lines(self, sample_journal):
        validator = JournalInvariantsValidator()
        result = validator.validate_all(sample_journal, [])
        assert result.is_valid is False
        assert "at least one line" in result.errors[0]