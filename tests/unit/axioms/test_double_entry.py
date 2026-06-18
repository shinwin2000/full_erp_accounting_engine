#!/usr/bin/env python3
"""Unit test untuk double entry axiom."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from axioms.double_entry import (
    DoubleEntryAxiom,
    DoubleEntryViolationError,
    JournalType,
    create_journal_line_dict,
    get_double_entry_axiom,
)


class TestDoubleEntryAxiom:
    @pytest.fixture
    def axiom(self) -> DoubleEntryAxiom:
        axiom = get_double_entry_axiom()
        axiom.reset()
        return axiom

        @pytest.fixture
        def valid_date(self) -> datetime:
            return datetime(2025, 1, 15, tzinfo=UTC)

            def test_balanced_journal_passes(self, axiom, valid_date):
                journal_id = uuid4()
                lines = [
                    create_journal_line_dict(
                        "1-1000", "debit", Decimal("1000"), description="Debit"
                    ),
                    create_journal_line_dict(
                        "4-1000", "credit", Decimal("1000"), description="Credit"
                    ),
                ]
                is_balanced, record, journal = axiom.enforce_from_lines(
                    journal_id=journal_id,
                    journal_number="JRN-202501-000001",
                    journal_type=JournalType.GENERAL,
                    lines=lines,
                    transaction_date=valid_date,
                    description="Balanced journal",
                    created_by="test_user",
                    auto_correct=True,
                    raise_on_violation=True,
                )
                assert is_balanced is True
                assert record.is_balanced is True
                assert journal.is_balanced() is True

                def test_unbalanced_journal_fails(self, axiom, valid_date):
                    journal_id = uuid4()
                    lines = [
                        create_journal_line_dict(
                            "1-1000", "debit", Decimal("1000"), description="Debit"
                        ),
                        create_journal_line_dict(
                            "4-1000", "credit", Decimal("900"), description="Credit"
                        ),
                    ]
                    # Match pattern disesuaikan dengan pesan exception yang sebenarnya
                    with pytest.raises(DoubleEntryViolationError, match="Double-entry violation"):
                        axiom.enforce_from_lines(
                            journal_id=journal_id,
                            journal_number="JRN-202501-000002",
                            journal_type=JournalType.GENERAL,
                            lines=lines,
                            transaction_date=valid_date,
                            description="Unbalanced journal",
                            created_by="test_user",
                            auto_correct=False,
                            raise_on_violation=True,
                        )

                        def test_verify_balance_simple(self, axiom):
                            is_balanced, diff, hint = axiom.verify_balance(
                                Decimal("1000"), Decimal("1000")
                            )
                            assert is_balanced is True
                            assert diff == 0
                            assert hint is None

                            def test_verify_balance_fails_large_difference(self, axiom):
                                is_balanced, diff, hint = axiom.verify_balance(
                                    Decimal("1000"), Decimal("900")
                                )
                                assert is_balanced is False
                                assert diff == Decimal("100")
                                assert hint is None

                                def test_verify_balance_small_difference_gives_hint(self, axiom):
                                    is_balanced, diff, hint = axiom.verify_balance(
                                        Decimal("1000.005"),
                                        Decimal("1000"),
                                        tolerance=Decimal("0.001"),
                                    )
                                    assert is_balanced is False
                                    assert diff == Decimal("0.005")
                                    assert hint is not None
                                    assert "Adjust" in hint

                                    if __name__ == "__main__":
                                        pytest.main([__file__])
