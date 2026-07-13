"""
Tests for domain/journal/journal_entry.py

Covers:
- JournalEntryStatus.from_string (incl. default fallback)
- JournalLine (simplified dataclass): validation, amount/side properties, to/from_dict
- JournalEntry (simplified dataclass): validation, total_debit/total_credit,
  is_balanced/is_posted, to_dict, create_draft factory
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.journal.journal_entry import JournalEntry, JournalEntryStatus, JournalLine


# ============================================================================
# JournalEntryStatus
# ============================================================================


class TestJournalEntryStatus:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("draft", JournalEntryStatus.DRAFT),
            ("DRAFT", JournalEntryStatus.DRAFT),
            ("posted", JournalEntryStatus.POSTED),
            ("reversed", JournalEntryStatus.REVERSED),
            ("adjusted", JournalEntryStatus.ADJUSTED),
            ("cancelled", JournalEntryStatus.CANCELLED),
        ],
    )
    def test_from_string_valid(self, raw, expected):
        assert JournalEntryStatus.from_string(raw) == expected

    def test_from_string_unknown_falls_back_to_draft(self):
        assert JournalEntryStatus.from_string("nonsense") == JournalEntryStatus.DRAFT


# ============================================================================
# JournalLine (simplified)
# ============================================================================


class TestJournalLineSimple:
    def test_valid_debit_line(self):
        line = JournalLine(account_code="1000", debit=Decimal("100"), credit=Decimal("0"))
        assert line.amount == Decimal("100")
        assert line.side == "debit"

    def test_valid_credit_line(self):
        line = JournalLine(account_code="4000", debit=Decimal("0"), credit=Decimal("100"))
        assert line.amount == Decimal("100")
        assert line.side == "credit"

    def test_negative_debit_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            JournalLine(account_code="1000", debit=Decimal("-1"), credit=Decimal("0"))

    def test_negative_credit_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            JournalLine(account_code="1000", debit=Decimal("0"), credit=Decimal("-1"))

    def test_both_debit_and_credit_raises(self):
        with pytest.raises(ValueError, match="cannot have both debit and credit"):
            JournalLine(account_code="1000", debit=Decimal("10"), credit=Decimal("10"))

    def test_both_zero_raises(self):
        with pytest.raises(ValueError, match="non-zero amount"):
            JournalLine(account_code="1000", debit=Decimal("0"), credit=Decimal("0"))

    def test_empty_account_code_raises(self):
        with pytest.raises(ValueError, match="Account code cannot be empty"):
            JournalLine(account_code="", debit=Decimal("10"), credit=Decimal("0"))

    def test_to_dict(self):
        line = JournalLine(
            account_code="1000", debit=Decimal("100"), credit=Decimal("0"),
            description="cash", cost_center="CC1", department="FIN",
        )
        d = line.to_dict()
        assert d == {
            "account_code": "1000",
            "debit": "100",
            "credit": "0",
            "description": "cash",
            "cost_center": "CC1",
            "department": "FIN",
        }

    def test_from_dict_round_trip(self):
        line = JournalLine(account_code="1000", debit=Decimal("55.5"), credit=Decimal("0"))
        restored = JournalLine.from_dict(line.to_dict())
        assert restored.account_code == line.account_code
        assert restored.debit == line.debit
        assert restored.credit == line.credit

    def test_from_dict_defaults(self):
        restored = JournalLine.from_dict({"account_code": "2000", "credit": "50"})
        assert restored.debit == Decimal("0")
        assert restored.credit == Decimal("50")
        assert restored.description == ""

    def test_line_is_immutable(self):
        line = JournalLine(account_code="1000", debit=Decimal("10"), credit=Decimal("0"))
        with pytest.raises(Exception):
            line.debit = Decimal("999")


# ============================================================================
# JournalEntry (simplified) — fixtures
# ============================================================================


def balanced_lines():
    return [
        JournalLine(account_code="1000", debit=Decimal("100"), credit=Decimal("0"), description="cash in"),
        JournalLine(account_code="4000", debit=Decimal("0"), credit=Decimal("100"), description="revenue"),
    ]


def make_entry(**overrides):
    defaults = dict(
        id=uuid4(),
        legal_entity_id=uuid4(),
        journal_number="JRN-100",
        journal_date=date(2026, 1, 15),
        period="2026-01",
        description="Test entry",
        source_system="ERP",
        status=JournalEntryStatus.DRAFT,
        created_by=uuid4(),
        created_at=datetime.now(UTC),
        lines=balanced_lines(),
    )
    defaults.update(overrides)
    return JournalEntry(**defaults)


# ============================================================================
# JournalEntry (simplified) — validation
# ============================================================================


class TestJournalEntryConstruction:
    def test_valid_entry(self):
        entry = make_entry()
        assert entry.is_balanced()
        assert not entry.is_posted()

    def test_short_description_raises(self):
        with pytest.raises(ValueError, match="Description must be at least 2 characters"):
            make_entry(description="x")

    def test_empty_description_raises(self):
        with pytest.raises(ValueError, match="Description must be at least 2 characters"):
            make_entry(description="")

    def test_no_lines_raises(self):
        with pytest.raises(ValueError, match="at least one line"):
            make_entry(lines=[])

    def test_unbalanced_lines_raise(self):
        unbalanced = [
            JournalLine(account_code="1000", debit=Decimal("100"), credit=Decimal("0")),
            JournalLine(account_code="4000", debit=Decimal("0"), credit=Decimal("50")),
        ]
        with pytest.raises(ValueError, match="not balanced"):
            make_entry(lines=unbalanced)


# ============================================================================
# JournalEntry (simplified) — behaviour
# ============================================================================


class TestJournalEntryBehaviour:
    def test_total_debit_and_credit(self):
        entry = make_entry()
        assert entry.total_debit == Decimal("100")
        assert entry.total_credit == Decimal("100")

    def test_is_posted_true_when_status_posted(self):
        entry = make_entry(status=JournalEntryStatus.POSTED)
        assert entry.is_posted() is True

    def test_is_posted_false_for_draft(self):
        entry = make_entry(status=JournalEntryStatus.DRAFT)
        assert entry.is_posted() is False

    def test_to_dict_contains_expected_fields(self):
        entry = make_entry()
        d = entry.to_dict()
        assert d["journal_number"] == "JRN-100"
        assert d["status"] == "draft"
        assert d["total_debit"] == "100"
        assert d["total_credit"] == "100"
        assert len(d["lines"]) == 2

    def test_to_dict_handles_none_optional_dates(self):
        entry = make_entry()
        d = entry.to_dict()
        assert d["posted_at"] is None
        assert d["reversed_at"] is None
        assert d["reversal_of"] is None

    def test_create_draft_factory(self):
        entry = JournalEntry.create_draft(
            legal_entity_id=uuid4(),
            journal_number="JRN-DRAFT-1",
            journal_date=date(2026, 2, 1),
            period="2026-02",
            description="Draft via factory",
            lines=balanced_lines(),
            created_by=uuid4(),
        )
        assert entry.status == JournalEntryStatus.DRAFT
        assert entry.source_system == "ERP"
        assert entry.is_balanced()

    def test_create_draft_with_custom_source_and_reference(self):
        entry = JournalEntry.create_draft(
            legal_entity_id=uuid4(),
            journal_number="JRN-DRAFT-2",
            journal_date=date(2026, 2, 1),
            period="2026-02",
            description="Draft via factory",
            lines=balanced_lines(),
            created_by=uuid4(),
            source_system="POS",
            reference="REF-1",
        )
        assert entry.source_system == "POS"
        assert entry.reference == "REF-1"

    def test_entry_is_immutable(self):
        entry = make_entry()
        with pytest.raises(Exception):
            entry.description = "changed"
