#!/usr/bin/env python3
"""Unit test untuk enforcement engine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from constitution.enforcement_engine import (
    EnforcementCatastrophicError,
    EnforcementContext,
    EnforcementEngine,
    EnforcementMode,
    EnforcementRejectedError,
    EnforcementReport,
    EnforcementResult,
)


class TestEnforcementEngine:
    """Test suite untuk EnforcementEngine."""

    @pytest.fixture
    def engine(self) -> EnforcementEngine:
        """Fresh singleton instance."""
        import constitution.enforcement_engine as module

        module._enforcement_engine_instance = None
        eng = EnforcementEngine()
        eng._report_history.clear()
        return eng

        @pytest.fixture
        def valid_context(self) -> EnforcementContext:
            """Konteks minimal (pipeline akan di-mock)."""
            return EnforcementContext(
                operation_id=uuid4(),
                operation_type="JOURNAL_POST",
                user_id="user123",
                user_roles=["ACCOUNTANT"],
                legal_entity_id=uuid4(),
                period_id=uuid4(),
                transaction_id=uuid4(),
                source="test",
                data={},
                mode=EnforcementMode.NORMAL,
            )

            @pytest.fixture
            def mock_pipeline(self, engine):
                """Mock pipeline.execute untuk mengembalikan report tertentu."""
                with patch.object(engine, "_pipeline") as mock:
                    yield mock

                    # -------------------------------------------------------------------------
                    # Helper: membuat mock report dengan atribut lengkap
                    # -------------------------------------------------------------------------
                    def _create_mock_report(self, final_result, rejection_reason=None):
                        mock_report = MagicMock(spec=EnforcementReport)
                        mock_report.final_result = final_result
                        mock_report.is_passed.return_value = final_result == EnforcementResult.PASS
                        mock_report.rejection_reason = rejection_reason
                        mock_report.stages_failed = []  # diperlukan oleh enforce() untuk menentukan stage
                        mock_report.stages_passed = []
                        mock_report.execution_time_ms = 10.0
                        mock_report.warning_count = 0
                        mock_report.warnings = []
                        mock_report.compute_hash = MagicMock(return_value="hash")
                        mock_report.report_id = uuid4()
                        mock_report.operation_id = uuid4()
                        mock_report.operation_type = "JOURNAL_POST"
                        mock_report.timestamp = datetime.now(UTC)
                        mock_report.required_approvers = []
                        mock_report.mode = EnforcementMode.NORMAL
                        mock_report.constitutional_hash = "hash"
                        return mock_report

                        # -------------------------------------------------------------------------
                        # Test 1: enforcement passes when pipeline returns PASS
                        # -------------------------------------------------------------------------
                        def test_enforce_passes_with_valid_context(
                            self, engine, valid_context, mock_pipeline
                        ):
                            mock_report = self._create_mock_report(EnforcementResult.PASS)
                            mock_pipeline.execute.return_value = mock_report

                            report = engine.enforce(valid_context)

                            assert report.final_result == EnforcementResult.PASS
                            assert report.is_passed()
                            assert report.rejection_reason is None

                            # -------------------------------------------------------------------------
                            # Test 2: enforcement raises EnforcementRejectedError when pipeline returns REJECTED
                            # -------------------------------------------------------------------------
                            def test_enforce_fails_on_rejection(
                                self, engine, valid_context, mock_pipeline
                            ):
                                mock_report = self._create_mock_report(
                                    EnforcementResult.REJECTED,
                                    rejection_reason="Test rejection reason",
                                )
                                mock_pipeline.execute.return_value = mock_report

                                with pytest.raises(
                                    EnforcementRejectedError, match="Test rejection reason"
                                ):
                                    engine.enforce(valid_context)

                                    # -------------------------------------------------------------------------
                                    # Test 3: enforcement raises EnforcementCatastrophicError when pipeline returns CATASTROPHIC
                                    # -------------------------------------------------------------------------
                                    def test_enforce_fails_catastrophic(
                                        self, engine, valid_context, mock_pipeline
                                    ):
                                        mock_report = self._create_mock_report(
                                            EnforcementResult.CATASTROPHIC,
                                            rejection_reason="Catastrophic failure",
                                        )
                                        mock_pipeline.execute.return_value = mock_report

                                        with pytest.raises(
                                            EnforcementCatastrophicError,
                                            match="Catastrophic failure",
                                        ):
                                            engine.enforce(valid_context)

                                            # -------------------------------------------------------------------------
                                            # Test 4: journal posting helper creates correct context and calls enforce
                                            # -------------------------------------------------------------------------
                                            def test_enforce_journal_posting_helper(self, engine):
                                                op_id = uuid4()
                                                leg_entity = uuid4()
                                                period_id = uuid4()

                                                mock_report = MagicMock()
                                                mock_report.final_result = EnforcementResult.PASS
                                                engine.enforce = MagicMock(return_value=mock_report)

                                                report = engine.enforce_journal_posting(
                                                    operation_id=op_id,
                                                    total_debit=Decimal("1000"),
                                                    total_credit=Decimal("1000"),
                                                    transaction_date=None,
                                                    legal_entity_id=leg_entity,
                                                    period_id=period_id,
                                                    user_id="user123",
                                                    user_roles=["ACCOUNTANT"],
                                                    source="test",
                                                    amount=Decimal("1000"),
                                                    data={"period_status": "OPEN"},
                                                )

                                                assert report.final_result == EnforcementResult.PASS
                                                call_args = engine.enforce.call_args[0][0]
                                                assert call_args.operation_type == "JOURNAL_POST"
                                                assert call_args.data["total_debit"] == Decimal(
                                                    "1000"
                                                )
                                                assert call_args.data["total_credit"] == Decimal(
                                                    "1000"
                                                )
                                                assert call_args.data["period_status"] == "OPEN"

                                                # -------------------------------------------------------------------------
                                                # Test 5: get_statistics returns correct numbers from history
                                                # -------------------------------------------------------------------------
                                                def test_get_statistics(self, engine):
                                                    # Tambahkan report langsung ke history dengan timestamp yang valid
                                                    for i in range(3):
                                                        report = EnforcementReport(
                                                            report_id=uuid4(),
                                                            operation_id=uuid4(),
                                                            operation_type="JOURNAL_POST",
                                                            timestamp=datetime(
                                                                2025, 1, 1, 12, 0, 0, tzinfo=UTC
                                                            ),
                                                            stages_passed=[],
                                                            stages_failed=[],
                                                            final_result=EnforcementResult.PASS,
                                                            rejection_reason=None,
                                                            required_approvers=[],
                                                            execution_time_ms=10.0 * (i + 1),
                                                            constitutional_hash="hash",
                                                            mode=EnforcementMode.NORMAL,
                                                        )
                                                        engine._report_history.append(report)

                                                        stats = engine.get_statistics()
                                                        # Production code uses key "total_enforcements", not "total"
                                                        assert stats["total_enforcements"] == 3
                                                        assert stats["passed"] == 3
                                                        assert stats["pass_rate"] == 1.0
                                                        assert "avg_execution_time_ms" in stats
                                                        assert (
                                                            stats["most_recent"]
                                                            == "2025-01-01T12:00:00+00:00"
                                                        )

                                                        # -------------------------------------------------------------------------
                                                        # Test 6: emergency bypass - success case
                                                        # -------------------------------------------------------------------------
                                                        def test_emergency_bypass(self, engine):
                                                            from constitution.sovereignty_declaration import (
                                                                SovereigntyStatus,
                                                            )

                                                            with patch(
                                                                "constitution.enforcement_engine.get_sovereignty_guardian"
                                                            ) as mock_sg:
                                                                guardian = MagicMock()
                                                                guardian.get_current_status = MagicMock(
                                                                    return_value=SovereigntyStatus.EMERGENCY_LOCKDOWN
                                                                )
                                                                mock_sg.return_value = guardian

                                                                with patch.object(
                                                                    engine, "_pipeline"
                                                                ) as mock_pipeline:
                                                                    mock_report = (
                                                                        self._create_mock_report(
                                                                            EnforcementResult.PASS
                                                                        )
                                                                    )
                                                                    mock_pipeline.execute.return_value = mock_report

                                                                    report = engine.emergency_bypass(
                                                                        operation_id=uuid4(),
                                                                        operation_type="JOURNAL_POST",
                                                                        data={
                                                                            "amount": Decimal(
                                                                                "1e12"
                                                                            )
                                                                        },
                                                                        user_id="admin",
                                                                        authorized_by=[
                                                                            "CEO",
                                                                            "CFO",
                                                                        ],
                                                                        reason="Disaster",
                                                                    )

                                                                    assert (
                                                                        report.final_result
                                                                        == EnforcementResult.PASS
                                                                    )
                                                                    assert (
                                                                        report.mode
                                                                        == EnforcementMode.EMERGENCY
                                                                    )
                                                                    assert (
                                                                        "EMERGENCY BYPASS"
                                                                        in report.warnings[0]
                                                                    )

                                                                    # -------------------------------------------------------------------------
                                                                    # Test 7: emergency bypass requires at least 2 authorizers
                                                                    # -------------------------------------------------------------------------
                                                                    def test_emergency_bypass_requires_two_authorizers(
                                                                        self, engine
                                                                    ):
                                                                        with pytest.raises(
                                                                            ValueError,
                                                                            match="at least 2 authorizers",
                                                                        ):
                                                                            engine.emergency_bypass(
                                                                                operation_id=uuid4(),
                                                                                operation_type="JOURNAL_POST",
                                                                                data={},
                                                                                user_id="admin",
                                                                                authorized_by=[
                                                                                    "CEO"
                                                                                ],
                                                                                reason="test",
                                                                            )

                                                                            if (
                                                                                __name__
                                                                                == "__main__"
                                                                            ):
                                                                                pytest.main(
                                                                                    [__file__]
                                                                                )
