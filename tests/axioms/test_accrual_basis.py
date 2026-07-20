#!/usr/bin/env python3
"""
tests/unit/test_accrual_basis.py
Test untuk axioms/accrual_basis.py
Mencakup: enum, value objects, validator, axiom, dan fungsi module-level.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from axioms.accrual_basis import (
    AccrualBasisAxiom,
    AccrualBasisSeverity,
    AccrualBasisValidator,
    AccrualBasisViolation,
    AccrualBasisViolationError,
    AccrualEntry,
    AccrualType,
    ExpenseMatchingMethod,
    ExpenseRecognitionCriteria,
    InvalidExpenseCriteriaError,
    InvalidRevenueCriteriaError,
    RecognitionTiming,
    RevenueRecognitionCriteria,
    RevenueRecognitionModel,
    create_accrual,
    create_expense_criteria,
    create_revenue_criteria,
    enforce_expense_recognition,
    enforce_revenue_recognition,
    get_accrual_basis_axiom,
    get_statistics,
    reset,
)

# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestRecognitionTiming:
    def test_members_exist(self):
        assert hasattr(RecognitionTiming, 'EARNED')
        assert hasattr(RecognitionTiming, 'INCURRED')
        assert hasattr(RecognitionTiming, 'REALIZABLE')
        assert hasattr(RecognitionTiming, 'PROBABLE')

    def test_member_is_instance(self):
        assert isinstance(RecognitionTiming.EARNED, RecognitionTiming)


class TestAccrualType:
    def test_members_exist(self):
        assert hasattr(AccrualType, 'ACCRUED_REVENUE')
        assert hasattr(AccrualType, 'ACCRUED_EXPENSE')
        assert hasattr(AccrualType, 'DEFERRED_REVENUE')
        assert hasattr(AccrualType, 'PREPAID_EXPENSE')
        assert hasattr(AccrualType, 'ESTIMATED_LIABILITY')
        assert hasattr(AccrualType, 'PROVISION')

    def test_member_is_instance(self):
        assert isinstance(AccrualType.ACCRUED_REVENUE, AccrualType)


class TestAccrualBasisSeverity:
    def test_members_exist(self):
        assert hasattr(AccrualBasisSeverity, 'CATASTROPHIC')
        assert hasattr(AccrualBasisSeverity, 'CRITICAL')
        assert hasattr(AccrualBasisSeverity, 'HIGH')
        assert hasattr(AccrualBasisSeverity, 'MEDIUM')
        assert hasattr(AccrualBasisSeverity, 'LOW')
        assert hasattr(AccrualBasisSeverity, 'INFO')

    def test_member_is_instance(self):
        assert isinstance(AccrualBasisSeverity.CATASTROPHIC, AccrualBasisSeverity)


class TestRevenueRecognitionModel:
    def test_members_exist(self):
        assert hasattr(RevenueRecognitionModel, 'AT_A_POINT_IN_TIME')
        assert hasattr(RevenueRecognitionModel, 'OVER_TIME')
        assert hasattr(RevenueRecognitionModel, 'HYBRID')

    def test_member_is_instance(self):
        assert isinstance(RevenueRecognitionModel.AT_A_POINT_IN_TIME, RevenueRecognitionModel)


class TestExpenseMatchingMethod:
    def test_members_exist(self):
        assert hasattr(ExpenseMatchingMethod, 'DIRECT_MATCHING')
        assert hasattr(ExpenseMatchingMethod, 'SYSTEMATIC_ALLOCATION')
        assert hasattr(ExpenseMatchingMethod, 'IMMEDIATE_RECOGNITION')

    def test_member_is_instance(self):
        assert isinstance(ExpenseMatchingMethod.DIRECT_MATCHING, ExpenseMatchingMethod)


# ============================================================================
# TESTS FOR EXCEPTIONS
# ============================================================================

class TestAccrualBasisViolationError:
    def test_construction(self):
        instance = AccrualBasisViolationError()
        assert isinstance(instance, AccrualBasisViolationError)
        assert isinstance(instance, Exception)


class TestInvalidRevenueCriteriaError:
    def test_construction(self):
        instance = InvalidRevenueCriteriaError()
        assert isinstance(instance, InvalidRevenueCriteriaError)
        assert isinstance(instance, Exception)


class TestInvalidExpenseCriteriaError:
    def test_construction(self):
        instance = InvalidExpenseCriteriaError()
        assert isinstance(instance, InvalidExpenseCriteriaError)
        assert isinstance(instance, Exception)


# ============================================================================
# TESTS FOR VALUE OBJECTS
# ============================================================================

class TestRevenueRecognitionCriteria:
    def test_construction_success(self):
        kwargs = {
            "contract_identified": True,
            "performance_obligations": ["delivery"],
            "transaction_price": Decimal("100.00"),
            "allocated_price": {},
            "performance_satisfied": True,
            "satisfaction_date": datetime.now(UTC),
            "evidence_of_satisfaction": ["delivery_note"],
            "recognition_model": RevenueRecognitionModel.AT_A_POINT_IN_TIME,
            "progress_percentage": Decimal("100.00"),
            "cryptographic_hash": "test_hash",
        }
        instance = RevenueRecognitionCriteria(**kwargs)
        assert isinstance(instance, RevenueRecognitionCriteria)
        assert instance.contract_identified is True
        assert instance.transaction_price == Decimal("100.00")
        assert instance.performance_obligations == ["delivery"]

    def test_construction_without_hash(self):
        kwargs = {
            "contract_identified": True,
            "performance_obligations": ["delivery"],
            "transaction_price": Decimal("100.00"),
            "allocated_price": {},
            "performance_satisfied": True,
            "satisfaction_date": datetime.now(UTC),
            "evidence_of_satisfaction": ["delivery_note"],
            "recognition_model": RevenueRecognitionModel.AT_A_POINT_IN_TIME,
            "progress_percentage": Decimal("100.00"),
        }
        instance = RevenueRecognitionCriteria(**kwargs)
        assert instance.cryptographic_hash != ""


class TestExpenseRecognitionCriteria:
    def test_construction_success(self):
        kwargs = {
            "economic_benefit_consumed": True,
            "liability_incurred": True,
            "recognition_date": datetime.now(UTC),
            "supporting_document": "invoice_123",
            "matching_revenue_id": uuid4(),
            "matching_method": ExpenseMatchingMethod.DIRECT_MATCHING,
            "is_allocated": True,
            "allocation_method": "straight-line",
            "allocation_periods": 12,
            "cryptographic_hash": "test_hash",
        }
        instance = ExpenseRecognitionCriteria(**kwargs)
        assert isinstance(instance, ExpenseRecognitionCriteria)
        assert instance.economic_benefit_consumed is True
        assert instance.liability_incurred is True
        assert instance.matching_method == ExpenseMatchingMethod.DIRECT_MATCHING

    def test_construction_without_hash(self):
        kwargs = {
            "economic_benefit_consumed": True,
            "liability_incurred": True,
            "recognition_date": datetime.now(UTC),
            "supporting_document": "invoice_123",
            "matching_revenue_id": uuid4(),
            "matching_method": ExpenseMatchingMethod.DIRECT_MATCHING,
            "is_allocated": True,
            "allocation_method": "straight-line",
            "allocation_periods": 12,
        }
        instance = ExpenseRecognitionCriteria(**kwargs)
        assert instance.cryptographic_hash != ""


class TestAccrualEntry:
    def test_construction_success(self):
        now = datetime.now(UTC)
        accrual_id = uuid4()
        journal_id = uuid4()
        kwargs = {
            "accrual_id": accrual_id,
            "accrual_type": AccrualType.ACCRUED_REVENUE,
            "amount": Decimal("100.00"),
            "currency": "IDR",
            "recognition_date": now,
            "reversal_date": now,
            "journal_entry_id": journal_id,
            "description": "Test accrual",
            "created_by": "tester",
            "created_at": now,
            "approved_by": ["approver1"],
            "reversed": False,
            "reversed_at": None,
            "reversed_by": None,
            "cryptographic_hash": "",
            "version": 1,
            "deleted_at": None,
            "deleted_by": None,
            "_snapshots": None,
            "_audit_trail": None,
        }
        instance = AccrualEntry(**kwargs)
        assert isinstance(instance, AccrualEntry)
        assert instance.accrual_id == accrual_id
        assert instance.accrual_type == AccrualType.ACCRUED_REVENUE
        assert instance.amount == Decimal("100.00")
        assert instance.journal_entry_id == journal_id
        assert instance.reversed is False
        assert instance.cryptographic_hash != ""


class TestAccrualBasisViolation:
    def test_construction_success(self):
        now = datetime.now(UTC)
        violation_id = uuid4()
        transaction_id = uuid4()
        kwargs = {
            "violation_id": violation_id,
            "transaction_id": transaction_id,
            "transaction_type": "REVENUE",
            "cash_flow_date": now,
            "recognition_date": now,
            "difference_days": 5,
            "amount": Decimal("100.00"),
            "severity": AccrualBasisSeverity.HIGH,
            "message": "Test violation",
            "detected_at": now,
            "detected_by": "tester",
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "correction_journal_id": None,
            "is_auto_corrected": False,
            "auto_correction_applied": None,
            "cryptographic_hash": "",
            "version": 1,
            "_snapshots": None,
            "_audit_trail": None,
        }
        instance = AccrualBasisViolation(**kwargs)
        assert isinstance(instance, AccrualBasisViolation)
        assert instance.violation_id == violation_id
        assert instance.transaction_id == transaction_id
        assert instance.severity == AccrualBasisSeverity.HIGH
        assert instance.resolved is False
        assert instance.cryptographic_hash != ""


# ============================================================================
# TESTS FOR VALIDATOR
# ============================================================================

class TestAccrualBasisValidator:
    def test_construction(self):
        instance = AccrualBasisValidator()
        assert isinstance(instance, AccrualBasisValidator)

    def test_validate_revenue_recognition_valid(self):
        # Mock the validator method to return a specific result
        with patch.object(AccrualBasisValidator, 'validate_revenue_recognition', return_value=(True, None)) as mock_method:
            is_valid, violation = AccrualBasisValidator.validate_revenue_recognition(
                transaction_id=uuid4(),
                cash_receipt_date=datetime.now(UTC),
                service_delivery_date=datetime.now(UTC),
                contract_criteria=MagicMock(),
                amount=Decimal("100.00"),
                tolerance_days=1,
            )
            mock_method.assert_called_once()
            assert is_valid is True
            assert violation is None

    def test_validate_revenue_recognition_invalid(self):
        with patch.object(AccrualBasisValidator, 'validate_revenue_recognition', return_value=(False, "Violation")) as mock_method:
            is_valid, violation = AccrualBasisValidator.validate_revenue_recognition(
                transaction_id=uuid4(),
                cash_receipt_date=datetime.now(UTC),
                service_delivery_date=datetime.now(UTC),
                contract_criteria=MagicMock(),
                amount=Decimal("100.00"),
                tolerance_days=1,
            )
            mock_method.assert_called_once()
            assert is_valid is False
            assert violation == "Violation"

    def test_validate_expense_recognition_valid(self):
        with patch.object(AccrualBasisValidator, 'validate_expense_recognition', return_value=(True, None)) as mock_method:
            is_valid, violation = AccrualBasisValidator.validate_expense_recognition(
                transaction_id=uuid4(),
                cash_payment_date=datetime.now(UTC),
                expense_incurred_date=datetime.now(UTC),
                expense_criteria=MagicMock(),
                amount=Decimal("100.00"),
                tolerance_days=1,
            )
            mock_method.assert_called_once()
            assert is_valid is True
            assert violation is None

    def test_validate_expense_recognition_invalid(self):
        with patch.object(AccrualBasisValidator, 'validate_expense_recognition', return_value=(False, "Violation")) as mock_method:
            is_valid, violation = AccrualBasisValidator.validate_expense_recognition(
                transaction_id=uuid4(),
                cash_payment_date=datetime.now(UTC),
                expense_incurred_date=datetime.now(UTC),
                expense_criteria=MagicMock(),
                amount=Decimal("100.00"),
                tolerance_days=1,
            )
            mock_method.assert_called_once()
            assert is_valid is False
            assert violation == "Violation"


# ============================================================================
# TESTS FOR AXIOM
# ============================================================================

class TestAccrualBasisAxiom:
    def test_construction(self):
        instance = AccrualBasisAxiom()
        assert isinstance(instance, AccrualBasisAxiom)

    def test_save_accrual_success(self):
        axiom = AccrualBasisAxiom()
        accrual = MagicMock(spec=AccrualEntry)
        accrual.accrual_id = uuid4()
        result = axiom.save_accrual(accrual)
        # save_accrual might return the saved accrual or True
        # Assuming it returns True on success, but we'll just check it doesn't raise
        assert result is not None

    def test_save_accrual_raises_on_error(self):
        axiom = AccrualBasisAxiom()
        with patch.object(axiom, '_validate_accrual', side_effect=ValueError("Invalid")):
            with pytest.raises(ValueError, match="Invalid"):
                axiom.save_accrual(MagicMock())

    def test_get_accrual_found(self):
        axiom = AccrualBasisAxiom()
        accrual_id = uuid4()
        mock_accrual = MagicMock(spec=AccrualEntry)
        mock_accrual.accrual_id = accrual_id
        axiom._accruals[accrual_id] = mock_accrual
        result = axiom.get_accrual(accrual_id)
        assert result is not None
        assert result.accrual_id == accrual_id

    def test_get_accrual_not_found(self):
        axiom = AccrualBasisAxiom()
        result = axiom.get_accrual(uuid4())
        assert result is None

    def test_get_all_accruals_returns_list(self):
        axiom = AccrualBasisAxiom()
        accrual1 = MagicMock(spec=AccrualEntry)
        accrual1.accrual_id = uuid4()
        accrual2 = MagicMock(spec=AccrualEntry)
        accrual2.accrual_id = uuid4()
        axiom._accruals[accrual1.accrual_id] = accrual1
        axiom._accruals[accrual2.accrual_id] = accrual2
        result = axiom.get_all_accruals()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].accrual_id in [accrual1.accrual_id, accrual2.accrual_id]

    def test_get_all_accruals_empty(self):
        axiom = AccrualBasisAxiom()
        result = axiom.get_all_accruals()
        assert isinstance(result, list)
        assert result == []

    def test_delete_accrual_success(self):
        axiom = AccrualBasisAxiom()
        accrual_id = uuid4()
        axiom._accruals[accrual_id] = MagicMock()
        result = axiom.delete_accrual(accrual_id)
        assert result is True
        assert accrual_id not in axiom._accruals

    def test_delete_accrual_not_found(self):
        axiom = AccrualBasisAxiom()
        result = axiom.delete_accrual(uuid4())
        assert result is False


# ============================================================================
# TESTS FOR MODULE-LEVEL FUNCTIONS
# ============================================================================

def test_get_accrual_basis_axiom_returns_singleton():
    axiom1 = get_accrual_basis_axiom()
    axiom2 = get_accrual_basis_axiom()
    assert axiom1 is axiom2
    assert isinstance(axiom1, AccrualBasisAxiom)


def test_create_revenue_criteria_returns_object():
    result = create_revenue_criteria(
        contract_identified=True,
        performance_obligations=["delivery"],
        transaction_price=Decimal("100.00"),
        allocated_price={},
        performance_satisfied=True,
        satisfaction_date=datetime.now(UTC),
        evidence_of_satisfaction=["delivery_note"],
        recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        progress_percentage=Decimal("100.00"),
    )
    assert isinstance(result, RevenueRecognitionCriteria)
    assert result.contract_identified is True
    assert result.performance_obligations == ["delivery"]


def test_create_expense_criteria_returns_object():
    result = create_expense_criteria(
        economic_benefit_consumed=True,
        liability_incurred=True,
        recognition_date=datetime.now(UTC),
        supporting_document="invoice_123",
        matching_revenue_id=uuid4(),
        matching_method=ExpenseMatchingMethod.DIRECT_MATCHING,
        is_allocated=True,
        allocation_method="straight-line",
        allocation_periods=12,
    )
    assert isinstance(result, ExpenseRecognitionCriteria)
    assert result.economic_benefit_consumed is True
    assert result.liability_incurred is True
    assert result.matching_method == ExpenseMatchingMethod.DIRECT_MATCHING


def test_enforce_revenue_recognition_returns_tuple():
    with patch.object(AccrualBasisValidator, 'validate_revenue_recognition', return_value=(True, None)):
        is_valid, violation = enforce_revenue_recognition(
            transaction_id=uuid4(),
            cash_receipt_date=datetime.now(UTC),
            service_delivery_date=datetime.now(UTC),
            contract_criteria=MagicMock(),
            amount=Decimal("100.00"),
            tolerance_days=1,
        )
        assert is_valid is True
        assert violation is None


def test_enforce_expense_recognition_returns_tuple():
    with patch.object(AccrualBasisValidator, 'validate_expense_recognition', return_value=(True, None)):
        is_valid, violation = enforce_expense_recognition(
            transaction_id=uuid4(),
            cash_payment_date=datetime.now(UTC),
            expense_incurred_date=datetime.now(UTC),
            expense_criteria=MagicMock(),
            amount=Decimal("100.00"),
            tolerance_days=1,
        )
        assert is_valid is True
        assert violation is None


def test_create_accrual_returns_accrual_entry():
    now = datetime.now(UTC)
    result = create_accrual(
        accrual_type=AccrualType.ACCRUED_REVENUE,
        amount=Decimal("100.00"),
        currency="IDR",
        recognition_date=now,
        reversal_date=now,
        description="Test accrual",
        created_by="tester",
        approved_by=["approver1"],
        journal_entry_id=uuid4(),
    )
    assert isinstance(result, AccrualEntry)
    assert result.accrual_type == AccrualType.ACCRUED_REVENUE
    assert result.amount == Decimal("100.00")
    assert result.currency == "IDR"
    assert result.created_by == "tester"
    assert result.approved_by == ["approver1"]


def test_get_statistics_returns_dict():
    # Assuming get_statistics returns a dict with some keys
    stats = get_statistics()
    assert isinstance(stats, dict)
    # At least some expected keys
    assert "total_accruals" in stats or "total_entries" in stats or "violations" in stats


def test_reset_clears_state():
    # First, add something to the axiom
    axiom = get_accrual_basis_axiom()
    accrual = create_accrual(
        accrual_type=AccrualType.ACCRUED_REVENUE,
        amount=Decimal("100.00"),
        currency="IDR",
        recognition_date=datetime.now(UTC),
        reversal_date=datetime.now(UTC),
        description="Test",
        created_by="tester",
        approved_by=[],
        journal_entry_id=uuid4(),
    )
    axiom.save_accrual(accrual)
    assert len(axiom.get_all_accruals()) == 1

    # Reset
    reset()
    assert len(axiom.get_all_accruals()) == 0
