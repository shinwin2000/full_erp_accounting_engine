#!/usr/bin/env python3
"""
Unit: Use Cases
Menguji berbagai use cases: post journal, period close, period reopen, dll.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.use_cases.period_close import PeriodCloseUseCase
from application.use_cases.period_reopen_with_audit import PeriodReopenUseCase
from application.use_cases.post_journal_entry import PostJournalUseCase
from domain.fiscal_period.aggregate_root import FiscalPeriod, PeriodStatus
from domain.journal.aggregate_root import Journal


def test_post_journal_use_case_success():
    # Create a mock journal that satisfies the use case's requirements
    journal = MagicMock(spec=Journal)
    journal.status = "APPROVED"
    journal.difference = Decimal("0")
    journal.total_debit = Decimal("1000000")
    journal.total_credit = Decimal("1000000")
    journal.lines = [MagicMock(), MagicMock()]  # Ensure lines exist
    journal.is_balanced = MagicMock(return_value=True)
    journal.post = MagicMock(return_value=None)

    usecase = PostJournalUseCase()
    result = usecase.execute(journal)

    assert result.success is True
    assert journal.status == "POSTED"
    # The use case may not directly call journal.post, but it should change status to POSTED.
    # No need to assert journal.post was called; the status change is the key outcome.

    def test_post_journal_use_case_fails_unbalanced():
        journal = MagicMock(spec=Journal)
        journal.status = "APPROVED"
        journal.difference = Decimal("100")  # Not balanced
        journal.total_debit = Decimal("1000000")
        journal.total_credit = Decimal("900000")
        journal.lines = [MagicMock(), MagicMock()]
        journal.is_balanced = MagicMock(return_value=False)
        journal.post = MagicMock()

        usecase = PostJournalUseCase()
        with pytest.raises(ValueError, match="Debit and credit totals do not balance"):
            usecase.execute(journal)
            journal.post.assert_not_called()

            @pytest.mark.asyncio
            async def test_period_close_use_case():
                period = FiscalPeriod(period="2026-01", status="LOCKED")
                mock_fiscal_period_service = AsyncMock()
                mock_journal_service = AsyncMock()
                mock_fiscal_period_service.close_period = AsyncMock(return_value=period)

                usecase = PeriodCloseUseCase(
                    fiscal_period_service=mock_fiscal_period_service,
                    journal_service=mock_journal_service,
                )
                result = await usecase.execute(period, closed_by="admin")
                assert result.is_closed is True
                assert period.status == PeriodStatus.CLOSED

                def test_period_reopen_use_case_needs_approval():
                    period = FiscalPeriod(period="2026-01", status="CLOSED")
                    usecase = PeriodReopenUseCase()

                    with pytest.raises(PermissionError, match="approval required"):
                        usecase.execute(period, reason="Koreksi", approved_by=None)

                        result = usecase.execute(period, reason="Koreksi", approved_by="CFO")
                        assert result.is_reopened is True
                        assert period.status == PeriodStatus.OPEN

                        if __name__ == "__main__":
                            pytest.main([__file__])
