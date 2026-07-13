"""
Tests for domain/journal/journal_line_vo.py

Covers:
- JournalSide enum: opposite(), is_debit(), is_credit(), from_string()
- JournalLineVO: construction + __post_init__ validation, is_debit/is_credit,
  net_amount, total_with_tax, normalize, to_dict/from_dict round trip,
  create_debit/create_credit factories, __hash__/__eq__, to_string/from_string
- JournalLineRepository: unimplemented protocol methods raise NotImplementedError
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from domain.journal.journal_line_vo import (
    JournalLine,
    JournalLineRepository,
    JournalLineVO,
    JournalSide,
)


# ============================================================================
# JournalSide
# ============================================================================


class TestJournalSide:
    def test_opposite_of_debit_is_credit(self):
        assert JournalSide.DEBIT.opposite() == JournalSide.CREDIT

    def test_opposite_of_credit_is_debit(self):
        assert JournalSide.CREDIT.opposite() == JournalSide.DEBIT

    def test_is_debit(self):
        assert JournalSide.DEBIT.is_debit() is True
        assert JournalSide.CREDIT.is_debit() is False

    def test_is_credit(self):
        assert JournalSide.CREDIT.is_credit() is True
        assert JournalSide.DEBIT.is_credit() is False

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("debit", JournalSide.DEBIT),
            ("DEBIT", JournalSide.DEBIT),
            ("dr", JournalSide.DEBIT),
            ("DR", JournalSide.DEBIT),
            ("d", JournalSide.DEBIT),
            ("credit", JournalSide.CREDIT),
            ("CREDIT", JournalSide.CREDIT),
            ("cr", JournalSide.CREDIT),
            ("c", JournalSide.CREDIT),
        ],
    )
    def test_from_string_valid(self, raw, expected):
        assert JournalSide.from_string(raw) == expected

    def test_from_string_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid journal side"):
            JournalSide.from_string("sideways")


# ============================================================================
# JournalLineVO — fixtures
# ============================================================================


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def journal_id():
    return uuid4()


def make_line(legal_entity_id, journal_id=None, **overrides):
    defaults = dict(
        line_id=uuid4(),
        journal_id=journal_id or uuid4(),
        account_id=uuid4(),
        account_code="1000",
        account_name="Cash",
        side=JournalSide.DEBIT,
        amount=Decimal("100.00"),
        description="Test line",
        legal_entity_id=legal_entity_id,
    )
    defaults.update(overrides)
    return JournalLineVO(**defaults)


# ============================================================================
# JournalLineVO — construction & validation
# ============================================================================


class TestJournalLineVOConstruction:
    def test_valid_construction(self, legal_entity_id):
        line = make_line(legal_entity_id)
        assert line.account_code == "1000"
        assert line.amount == Decimal("100.00")
        assert line.currency == "IDR"
        assert line.tax_rate == Decimal(0)
        assert line.tax_amount == Decimal(0)

    def test_amount_zero_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Amount must be positive"):
            make_line(legal_entity_id, amount=Decimal("0"))

    def test_amount_negative_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Amount must be positive"):
            make_line(legal_entity_id, amount=Decimal("-10"))

    def test_amount_exceeds_maximum_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Amount exceeds maximum"):
            make_line(legal_entity_id, amount=Decimal("10000000000000.00"))

    def test_amount_at_maximum_is_allowed(self, legal_entity_id):
        line = make_line(legal_entity_id, amount=Decimal("9999999999999.99"))
        assert line.amount == Decimal("9999999999999.99")

    def test_empty_account_code_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Account code cannot be empty"):
            make_line(legal_entity_id, account_code="")

    def test_empty_description_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Description cannot be empty"):
            make_line(legal_entity_id, description="")

    def test_description_too_short_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Description too short"):
            make_line(legal_entity_id, description="A")

    def test_description_min_length_is_allowed(self, legal_entity_id):
        line = make_line(legal_entity_id, description="AB")
        assert line.description == "AB"

    def test_tax_rate_negative_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            make_line(legal_entity_id, tax_rate=Decimal("-1"))

    def test_tax_rate_over_100_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            make_line(legal_entity_id, tax_rate=Decimal("101"))

    def test_tax_amount_negative_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            make_line(legal_entity_id, tax_amount=Decimal("-5"))

    def test_line_is_immutable(self, legal_entity_id):
        line = make_line(legal_entity_id)
        with pytest.raises(Exception):
            line.amount = Decimal("999")  # frozen dataclass


# ============================================================================
# JournalLineVO — behaviour
# ============================================================================


class TestJournalLineVOBehaviour:
    def test_is_debit_and_is_credit(self, legal_entity_id):
        debit_line = make_line(legal_entity_id, side=JournalSide.DEBIT)
        credit_line = make_line(legal_entity_id, side=JournalSide.CREDIT)
        assert debit_line.is_debit() is True
        assert debit_line.is_credit() is False
        assert credit_line.is_credit() is True
        assert credit_line.is_debit() is False

    def test_net_amount_equals_amount(self, legal_entity_id):
        line = make_line(legal_entity_id, amount=Decimal("250.50"))
        assert line.net_amount() == Decimal("250.50")

    def test_total_with_tax(self, legal_entity_id):
        line = make_line(legal_entity_id, amount=Decimal("100"), tax_amount=Decimal("11"))
        assert line.total_with_tax() == Decimal("111")

    def test_normalize_strips_and_formats_fields(self, legal_entity_id):
        line = make_line(
            legal_entity_id,
            account_code="  1000  ",
            account_name="  cash on hand  ",
            description="  spaced desc  ",
            cost_center="  cc01  ",
            department="  finance  ",
            currency="idr",
            amount=Decimal("100.005"),
            tax_rate=Decimal("11.005"),
            tax_amount=Decimal("5.005"),
        )
        normalized = line.normalize()
        assert normalized.account_code == "1000"
        assert normalized.account_name == "Cash On Hand"
        assert normalized.description == "spaced desc"
        assert normalized.cost_center == "CC01"
        assert normalized.department == "FINANCE"
        assert normalized.currency == "IDR"
        # ROUND_HALF_EVEN is decimal default; just check 2 decimal places
        assert normalized.amount == normalized.amount.quantize(Decimal("0.01"))

    def test_normalize_handles_none_optional_fields(self, legal_entity_id):
        line = make_line(legal_entity_id, cost_center=None, department=None)
        normalized = line.normalize()
        assert normalized.cost_center is None
        assert normalized.department is None

    def test_to_dict_contains_expected_keys(self, legal_entity_id):
        line = make_line(legal_entity_id)
        d = line.to_dict()
        expected_keys = {
            "line_id", "journal_id", "account_id", "account_code", "account_name",
            "side", "amount", "description", "legal_entity_id", "cost_center",
            "department", "project_id", "customer_id", "supplier_id", "employee_id",
            "currency", "tax_rate", "tax_amount",
        }
        assert expected_keys.issubset(d.keys())
        assert d["side"] == "debit"
        assert d["amount"] == "100.00"

    def test_to_dict_none_optional_ids_are_none(self, legal_entity_id):
        line = make_line(legal_entity_id)
        d = line.to_dict()
        assert d["project_id"] is None
        assert d["customer_id"] is None
        assert d["supplier_id"] is None
        assert d["employee_id"] is None

    def test_from_dict_round_trip(self, legal_entity_id):
        line = make_line(legal_entity_id, tax_rate=Decimal("11"), tax_amount=Decimal("11"))
        d = line.to_dict()
        restored = JournalLineVO.from_dict(d)
        assert restored.account_code == line.account_code
        assert restored.amount == line.amount
        assert restored.side == line.side
        assert restored.legal_entity_id == line.legal_entity_id
        assert restored.tax_rate == line.tax_rate

    def test_from_dict_generates_new_line_id_if_missing(self, legal_entity_id, journal_id):
        d = {
            "journal_id": str(journal_id),
            "account_id": str(uuid4()),
            "account_code": "1000",
            "account_name": "Cash",
            "side": "debit",
            "amount": "50",
            "description": "no line id",
            "legal_entity_id": str(legal_entity_id),
        }
        restored = JournalLineVO.from_dict(d)
        assert restored.line_id is not None

    def test_create_debit_factory(self, legal_entity_id, journal_id):
        line = JournalLineVO.create_debit(
            journal_id, uuid4(), "1000", "Cash", Decimal("100"), "debit line", legal_entity_id
        )
        assert line.side == JournalSide.DEBIT
        assert line.is_debit()

    def test_create_credit_factory(self, legal_entity_id, journal_id):
        line = JournalLineVO.create_credit(
            journal_id, uuid4(), "4000", "Revenue", Decimal("100"), "credit line", legal_entity_id
        )
        assert line.side == JournalSide.CREDIT
        assert line.is_credit()

    def test_create_debit_accepts_extra_kwargs(self, legal_entity_id, journal_id):
        line = JournalLineVO.create_debit(
            journal_id, uuid4(), "1000", "Cash", Decimal("100"), "debit line",
            legal_entity_id, cost_center="CC1", currency="USD",
        )
        assert line.cost_center == "CC1"
        assert line.currency == "USD"

    def test_hash_based_on_line_id(self, legal_entity_id):
        line = make_line(legal_entity_id)
        assert hash(line) == hash(
            (line.line_id, line.journal_id, line.account_id, line.side, line.amount)
        )

    def test_equality_based_on_line_id_only(self, legal_entity_id):
        shared_id = uuid4()
        line_a = make_line(legal_entity_id, line_id=shared_id, amount=Decimal("100"))
        line_b = make_line(legal_entity_id, line_id=shared_id, amount=Decimal("999"))
        assert line_a == line_b  # equality only compares line_id

    def test_inequality_with_different_line_id(self, legal_entity_id):
        line_a = make_line(legal_entity_id)
        line_b = make_line(legal_entity_id)
        assert line_a != line_b

    def test_equality_with_non_journal_line_vo_is_false(self, legal_entity_id):
        line = make_line(legal_entity_id)
        assert (line == "not a line") is False

    def test_to_string_and_from_string_round_trip(self, legal_entity_id):
        line = make_line(
            legal_entity_id, account_code="1000", side=JournalSide.DEBIT,
            amount=Decimal("100"), description="round trip desc",
        )
        s = line.to_string()
        assert s == "1000|debit|100|round trip desc"
        restored = JournalLineVO.from_string(s)
        assert restored.account_code == "1000"
        assert restored.side == JournalSide.DEBIT
        assert restored.amount == Decimal("100")
        assert restored.description == "round trip desc"

    def test_from_string_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid line string"):
            JournalLineVO.from_string("only|two")

    def test_journal_line_alias_is_journal_line_vo(self):
        assert JournalLine is JournalLineVO


# ============================================================================
# JournalLineRepository — unimplemented protocol
# ============================================================================


class TestJournalLineRepository:
    @pytest.fixture
    def repo(self):
        return JournalLineRepository()

    async def test_get_by_journal_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_journal(uuid4(), uuid4())

    async def test_get_by_account_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_account(uuid4(), uuid4())

    async def test_save_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.save(make_line(uuid4()))

    async def test_save_many_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.save_many([])

    async def test_delete_by_journal_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.delete_by_journal(uuid4(), uuid4())
