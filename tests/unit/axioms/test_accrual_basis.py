#!/usr/bin/env python3
"""Unit test untuk accrual basis axiom."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from axioms.accrual_basis import (
    AccrualBasisAxiom,
    AccrualBasisViolationError,
    AccrualType,
    ExpenseMatchingMethod,
    RevenueRecognitionModel,
    create_expense_criteria,
    create_revenue_criteria,
    get_accrual_basis_axiom,
)


class TestAccrualBasisAxiom:
    @pytest.fixture
    def axiom(self) -> AccrualBasisAxiom:
        axiom = get_accrual_basis_axiom()
        axiom.reset()
        return axiom

        @pytest.fixture
        def base_revenue_criteria(self) -> dict:
            return {
                "contract_identified": True,
                "performance_obligations": ["Deliver goods"],
                "transaction_price": Decimal("1000000"),
                "allocated_price": {"Deliver goods": Decimal("1000000")},
                "performance_satisfied": True,
                "evidence": ["delivery_note_123"],
                "recognition_model": RevenueRecognitionModel.AT_A_POINT_IN_TIME,
                "progress_percentage": Decimal(0),
            }

            @pytest.fixture
            def valid_expense_criteria(self) -> dict:
                return {
                    "benefit_consumed": True,
                    "liability_incurred": True,
                    "recognition_date": datetime(2025, 1, 15, tzinfo=UTC),
                    "supporting_document": "invoice_456",
                    "matching_revenue_id": None,
                    "matching_method": ExpenseMatchingMethod.IMMEDIATE_RECOGNITION,
                }

                # ========================================================================
                # REVENUE TESTS
                # ========================================================================

                def test_revenue_recorded_at_correct_time(self, axiom, base_revenue_criteria):
                    transaction_id = uuid4()
                    cash_receipt_date = datetime(2025, 1, 15, tzinfo=UTC)
                    satisfaction_date = datetime(2025, 1, 15, tzinfo=UTC)

                    criteria = create_revenue_criteria(
                        satisfaction_date=satisfaction_date,
                        **base_revenue_criteria,
                    )

                    is_valid, violation = axiom.enforce_revenue_recognition(
                        transaction_id=transaction_id,
                        cash_receipt_date=cash_receipt_date,
                        service_delivery_date=satisfaction_date,
                        contract_criteria=criteria,
                        amount=Decimal("1000000"),
                        tolerance_days=7,
                        raise_on_violation=True,
                    )
                    assert is_valid is True
                    assert violation is None

                    def test_revenue_recorded_too_late_raises_violation(
                        self, axiom, base_revenue_criteria
                    ):
                        transaction_id = uuid4()
                        cash_receipt_date = datetime(2025, 1, 15, tzinfo=UTC)
                        satisfaction_date = datetime(2025, 2, 15, tzinfo=UTC)  # 31 days later

                        criteria = create_revenue_criteria(
                            satisfaction_date=satisfaction_date,
                            **base_revenue_criteria,
                        )

                        with pytest.raises(AccrualBasisViolationError, match="timing mismatch"):
                            axiom.enforce_revenue_recognition(
                                transaction_id=transaction_id,
                                cash_receipt_date=cash_receipt_date,
                                service_delivery_date=satisfaction_date,
                                contract_criteria=criteria,
                                amount=Decimal("1000000"),
                                tolerance_days=7,
                                raise_on_violation=True,
                            )

                            def test_revenue_criteria_not_met_raises_violation(
                                self, axiom, base_revenue_criteria
                            ):
                                transaction_id = uuid4()
                                cash_receipt_date = datetime(2025, 1, 15, tzinfo=UTC)
                                satisfaction_date = datetime(2025, 1, 15, tzinfo=UTC)

                                # Override performance_satisfied to False
                                criteria_dict = base_revenue_criteria.copy()
                                criteria_dict["performance_satisfied"] = False
                                criteria_dict["satisfaction_date"] = satisfaction_date
                                criteria = create_revenue_criteria(**criteria_dict)

                                with pytest.raises(
                                    AccrualBasisViolationError, match="criteria not met"
                                ):
                                    axiom.enforce_revenue_recognition(
                                        transaction_id=transaction_id,
                                        cash_receipt_date=cash_receipt_date,
                                        service_delivery_date=satisfaction_date,
                                        contract_criteria=criteria,
                                        amount=Decimal("1000000"),
                                        tolerance_days=7,
                                        raise_on_violation=True,
                                    )

                                    # ========================================================================
                                    # EXPENSE TESTS
                                    # ========================================================================

                                    def test_expense_recorded_at_correct_time(
                                        self, axiom, valid_expense_criteria
                                    ):
                                        transaction_id = uuid4()
                                        payment_date = datetime(2025, 1, 15, tzinfo=UTC)
                                        expense_incurred_date = datetime(2025, 1, 15, tzinfo=UTC)
                                        criteria = create_expense_criteria(**valid_expense_criteria)

                                        is_valid, violation = axiom.enforce_expense_recognition(
                                            transaction_id=transaction_id,
                                            payment_date=payment_date,
                                            expense_incurred_date=expense_incurred_date,
                                            criteria=criteria,
                                            amount=Decimal("500000"),
                                            tolerance_days=7,
                                            raise_on_violation=True,
                                        )
                                        assert is_valid is True
                                        assert violation is None

                                        def test_expense_recorded_too_early_raises_violation(
                                            self, axiom, valid_expense_criteria
                                        ):
                                            transaction_id = uuid4()
                                            payment_date = datetime(2025, 1, 15, tzinfo=UTC)
                                            expense_incurred_date = datetime(
                                                2025, 2, 1, tzinfo=UTC
                                            )  # 17 days later
                                            criteria = create_expense_criteria(
                                                **valid_expense_criteria
                                            )

                                            with pytest.raises(
                                                AccrualBasisViolationError, match="timing mismatch"
                                            ):
                                                axiom.enforce_expense_recognition(
                                                    transaction_id=transaction_id,
                                                    payment_date=payment_date,
                                                    expense_incurred_date=expense_incurred_date,
                                                    criteria=criteria,
                                                    amount=Decimal("500000"),
                                                    tolerance_days=7,
                                                    raise_on_violation=True,
                                                )

                                                # ========================================================================
                                                # ACCRUAL TESTS
                                                # ========================================================================

                                                def test_create_accrual(self, axiom):
                                                    recognition_date = datetime(
                                                        2025, 1, 31, tzinfo=UTC
                                                    )
                                                    reversal_date = datetime(
                                                        2025, 2, 10, tzinfo=UTC
                                                    )

                                                    accrual = axiom.create_accrual(
                                                        accrual_type=AccrualType.ACCRUED_REVENUE,
                                                        amount=Decimal("750000"),
                                                        currency="IDR",
                                                        recognition_date=recognition_date,
                                                        description="Pendapatan jasa bulan Januari",
                                                        created_by="accountant1",
                                                        approved_by=["finance_manager"],
                                                        reversal_date=reversal_date,
                                                        journal_entry_id=None,
                                                    )

                                                    assert accrual is not None
                                                    assert (
                                                        accrual.accrual_type
                                                        == AccrualType.ACCRUED_REVENUE
                                                    )
                                                    assert accrual.amount == Decimal("750000")
                                                    assert accrual.currency == "IDR"
                                                    assert (
                                                        accrual.recognition_date == recognition_date
                                                    )
                                                    assert accrual.reversal_date == reversal_date
                                                    assert accrual.reversed is False

                                                    # Active before reversal date
                                                    before_reversal = reversal_date - timedelta(
                                                        days=1
                                                    )
                                                    assert (
                                                        accrual.is_active(as_of=before_reversal)
                                                        is True
                                                    )

                                                    # Not active after reversal date
                                                    after_reversal = reversal_date + timedelta(
                                                        days=1
                                                    )
                                                    assert (
                                                        accrual.is_active(as_of=after_reversal)
                                                        is False
                                                    )

                                                    # Manual reversal
                                                    reversed_accrual = axiom.reverse_accrual(
                                                        accrual.accrual_id,
                                                        reversed_by="accountant1",
                                                    )
                                                    assert reversed_accrual is not None
                                                    assert reversed_accrual.reversed is True
                                                    assert (
                                                        reversed_accrual.reversed_by
                                                        == "accountant1"
                                                    )

                                                    def test_get_accruals(self, axiom):
                                                        for i in range(3):
                                                            axiom.create_accrual(
                                                                accrual_type=AccrualType.ACCRUED_EXPENSE,
                                                                amount=Decimal(f"100000{i + 1}"),
                                                                currency="IDR",
                                                                recognition_date=datetime(
                                                                    2025, 1, 31, tzinfo=UTC
                                                                ),
                                                                description=f"Expense {i + 1}",
                                                                created_by="user",
                                                                approved_by=["manager"],
                                                                reversal_date=None,
                                                            )

                                                            all_accruals = axiom.get_accruals()
                                                            assert len(all_accruals) == 3

                                                            expense_accruals = axiom.get_accruals(
                                                                accrual_type=AccrualType.ACCRUED_EXPENSE
                                                            )
                                                            assert len(expense_accruals) == 3

                                                            revenue_accruals = axiom.get_accruals(
                                                                accrual_type=AccrualType.ACCRUED_REVENUE
                                                            )
                                                            assert len(revenue_accruals) == 0

                                                            # ========================================================================
                                                            # STATISTICS TEST
                                                            # ========================================================================

                                                            def test_statistics(
                                                                self, axiom, base_revenue_criteria
                                                            ):
                                                                # Valid transaction
                                                                tx1 = uuid4()
                                                                criteria_ok = (
                                                                    create_revenue_criteria(
                                                                        satisfaction_date=datetime(
                                                                            2025, 1, 15, tzinfo=UTC
                                                                        ),
                                                                        **base_revenue_criteria,
                                                                    )
                                                                )
                                                                axiom.enforce_revenue_recognition(
                                                                    transaction_id=tx1,
                                                                    cash_receipt_date=datetime(
                                                                        2025, 1, 15, tzinfo=UTC
                                                                    ),
                                                                    service_delivery_date=datetime(
                                                                        2025, 1, 15, tzinfo=UTC
                                                                    ),
                                                                    contract_criteria=criteria_ok,
                                                                    amount=Decimal("1000000"),
                                                                    raise_on_violation=False,
                                                                )

                                                                # Violation transaction
                                                                tx2 = uuid4()
                                                                criteria_late = (
                                                                    create_revenue_criteria(
                                                                        satisfaction_date=datetime(
                                                                            2025, 2, 15, tzinfo=UTC
                                                                        ),
                                                                        **base_revenue_criteria,
                                                                    )
                                                                )
                                                                with pytest.raises(
                                                                    AccrualBasisViolationError
                                                                ):
                                                                    axiom.enforce_revenue_recognition(
                                                                        transaction_id=tx2,
                                                                        cash_receipt_date=datetime(
                                                                            2025, 1, 15, tzinfo=UTC
                                                                        ),
                                                                        service_delivery_date=datetime(
                                                                            2025, 2, 15, tzinfo=UTC
                                                                        ),
                                                                        contract_criteria=criteria_late,
                                                                        amount=Decimal("2000000"),
                                                                        tolerance_days=7,
                                                                        raise_on_violation=True,
                                                                    )

                                                                    stats = axiom.get_statistics()
                                                                    assert (
                                                                        stats["total_accruals"] == 0
                                                                    )
                                                                    assert (
                                                                        stats["total_violations"]
                                                                        >= 1
                                                                    )
                                                                    assert (
                                                                        stats[
                                                                            "unresolved_violations"
                                                                        ]
                                                                        >= 1
                                                                    )

                                                                    if __name__ == "__main__":
                                                                        pytest.main([__file__])
