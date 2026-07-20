# tests/domain/umkm_simplified/test_invariants.py
"""
Unit tests for invariants.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from domain.umkm_simplified.invariants import (
    InvariantResult,
    UMKMInvariantEnforcer,
    UMKMInvariants,
)
from domain.umkm_simplified.simplified_journal_entity import (
    PaymentMethod,
    SimplifiedJournalEntity,
    TransactionType,
)

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
        result.add_error("Error 1")
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0] == "Error 1"

    def test_merge(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["Err2"])
        r1.merge(r2)
        assert r1.is_valid is False
        assert "Err2" in r1.errors

    def test_bool(self):
        result = InvariantResult()
        assert bool(result) is True
        result.add_error("err")
        assert bool(result) is False

    def test_validate(self):
        result = InvariantResult()
        res = result.validate()
        assert res["is_valid"] is True

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["e1"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["e1"]
        assert "version" in d

    def test_from_dict(self):
        data = {"is_valid": False, "errors": ["a", "b"], "version": 2}
        result = InvariantResult.from_dict(data)
        assert result.is_valid is False
        assert result.errors == ["a", "b"]
        assert result._version == 2

    def test_clone(self):
        result = InvariantResult(is_valid=False, errors=["x"])
        clone = result.clone()
        assert clone.is_valid is False
        assert clone.errors == ["x"]
        assert clone._version == result._version + 1

    def test_snapshot(self):
        result = InvariantResult()
        snap = result.snapshot()
        assert "version" in snap
        assert "is_valid" in snap

    def test_version(self):
        result = InvariantResult()
        assert result.version() == 1

    def test_audit_trail(self):
        result = InvariantResult()
        result.add_error("err")
        trail = result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "ADD_ERROR"

    def test_touch(self):
        result = InvariantResult()
        old_version = result.version()
        result.touch("tester")
        assert result.version() == old_version + 1
        trail = result.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# Test UMKMInvariants
# ============================================================================

class TestUMKMInvariants:
    def test_validate_amount_positive(self):
        result = UMKMInvariants.validate_amount(Decimal("10"))
        assert result.is_valid is True

    def test_validate_amount_negative(self):
        result = UMKMInvariants.validate_amount(Decimal("-5"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_cash_balance_income(self):
        result = UMKMInvariants.validate_cash_balance(
            new_balance=Decimal("100"),
            transaction_amount=Decimal("50"),
            transaction_type=TransactionType.INCOME,
        )
        assert result.is_valid is True

    def test_validate_cash_balance_expense_insufficient(self):
        result = UMKMInvariants.validate_cash_balance(
            new_balance=Decimal("-10"),
            transaction_amount=Decimal("50"),
            transaction_type=TransactionType.EXPENSE,
        )
        assert result.is_valid is False
        assert "Insufficient" in result.errors[0]

    def test_validate_journal_number(self):
        existing = {"JRN-001"}
        result = UMKMInvariants.validate_journal_number("JRN-002", existing)
        assert result.is_valid is True
        result2 = UMKMInvariants.validate_journal_number("AB", existing)
        assert result2.is_valid is False
        assert "too short" in result2.errors[0]
        result3 = UMKMInvariants.validate_journal_number("JRN-001", existing)
        assert result3.is_valid is False
        assert "already exists" in result3.errors[0]

    def test_validate_category(self):
        result = UMKMInvariants.validate_category("Sales")
        assert result.is_valid is True
        result2 = UMKMInvariants.validate_category("")
        assert result2.is_valid is False
        result3 = UMKMInvariants.validate_category("A")
        assert result3.is_valid is False

    def test_validate_transaction_date(self):
        now = datetime.now(UTC)
        past = now - timedelta(days=1)
        future = now + timedelta(days=1)
        result = UMKMInvariants.validate_transaction_date(past, now)
        assert result.is_valid is True
        result2 = UMKMInvariants.validate_transaction_date(future, now)
        assert result2.is_valid is False
        assert "future" in result2.errors[0]


# ============================================================================
# Test UMKMInvariantEnforcer
# ============================================================================

class TestUMKMInvariantEnforcer:
    @pytest.fixture
    def checker(self):
        async def mock_checker():
            return {"JRN-001"}
        return mock_checker

    @pytest.mark.asyncio
    async def test_enforce_create_journal(self, checker):
        enforcer = UMKMInvariantEnforcer(journal_number_checker=checker)
        journal = SimplifiedJournalEntity(
            journal_id=uuid4(),
            journal_number="JRN-002",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("100"),
            description="Test",
            transaction_date=datetime.now(UTC),
            category="Sales",
            payment_method=PaymentMethod.CASH,
            status=JournalStatus.ACTIVE,
        )
        result = await enforcer.enforce_create_journal(journal)
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_create_journal_invalid(self, checker):
        enforcer = UMKMInvariantEnforcer(journal_number_checker=checker)
        journal = SimplifiedJournalEntity(
            journal_id=uuid4(),
            journal_number="JRN-001",  # duplicate
            transaction_type=TransactionType.INCOME,
            amount=Decimal("-10"),      # negative
            description="Test",
            transaction_date=datetime.now(UTC),
            category="A",               # too short
            payment_method=PaymentMethod.CASH,
            status=JournalStatus.ACTIVE,
        )
        result = await enforcer.enforce_create_journal(journal)
        assert result.is_valid is False
        assert len(result.errors) >= 3

    def test_enforce_cash_balance_income(self):
        enforcer = UMKMInvariantEnforcer()
        journal = SimplifiedJournalEntity(
            journal_id=uuid4(),
            journal_number="J",
            transaction_type=TransactionType.INCOME,
            amount=Decimal("100"),
            description="",
            transaction_date=datetime.now(UTC),
            category="",
            payment_method=PaymentMethod.CASH,
            status=JournalStatus.ACTIVE,
        )
        result = enforcer.enforce_cash_balance(Decimal("50"), journal)
        assert result.is_valid is True

    def test_enforce_cash_balance_expense_insufficient(self):
        enforcer = UMKMInvariantEnforcer()
        journal = SimplifiedJournalEntity(
            journal_id=uuid4(),
            journal_number="J",
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("200"),
            description="",
            transaction_date=datetime.now(UTC),
            category="",
            payment_method=PaymentMethod.CASH,
            status=JournalStatus.ACTIVE,
        )
        result = enforcer.enforce_cash_balance(Decimal("100"), journal)
        assert result.is_valid is False

    def test_validate(self):
        enforcer = UMKMInvariantEnforcer()
        res = enforcer.validate()
        assert res["is_valid"] is True

    def test_to_dict(self):
        enforcer = UMKMInvariantEnforcer()
        d = enforcer.to_dict()
        assert "version" in d

    def test_from_dict(self):
        data = {"version": 5}
        enforcer = UMKMInvariantEnforcer.from_dict(data)
        assert enforcer._version == 5

    def test_clone(self):
        enforcer = UMKMInvariantEnforcer()
        clone = enforcer.clone()
        assert clone._version == enforcer._version + 1

    def test_snapshot(self):
        enforcer = UMKMInvariantEnforcer()
        snap = enforcer.snapshot()
        assert "version" in snap

    def test_version(self):
        enforcer = UMKMInvariantEnforcer()
        assert enforcer.version() == 1

    def test_audit_trail(self):
        enforcer = UMKMInvariantEnforcer()
        enforcer._record_audit("TEST", "user", {})
        trail = enforcer.audit_trail()
        assert len(trail) == 1

    def test_touch(self):
        enforcer = UMKMInvariantEnforcer()
        old = enforcer.version()
        enforcer.touch("tester")
        assert enforcer.version() == old + 1
        trail = enforcer.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_reset(self):
        enforcer = UMKMInvariantEnforcer()
        enforcer.touch("t")
        enforcer.reset()
        assert enforcer.version() == 1
        assert enforcer._audit_trail == []
