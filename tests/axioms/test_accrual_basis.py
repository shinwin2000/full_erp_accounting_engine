#!/usr/bin/env python3
"""
tests/unit/test_accrual_basis.py
Test untuk axioms/accrual_basis.py
Mencakup: enum, value objects, validator, axiom, dan fungsi module-level.
"""

from datetime import UTC, datetime, timedelta
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
# FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def reset_axiom():
    """Reset the singleton axiom before each test to avoid cross-test pollution."""
    axiom = get_accrual_basis_axiom()
    axiom.reset()
    yield


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
        instance = RevenueRecognitionCriteria(
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
        assert isinstance(instance, RevenueRecognitionCriteria)
        assert instance.contract_identified is True
        assert instance.transaction_price == Decimal("100.00")
        assert instance.performance_obligations == ["delivery"]
        assert instance.cryptographic_hash != ""

    def test_construction_with_valid_hash(self):
        # Buat instance sementara untuk mendapatkan hash yang valid
        temp = RevenueRecognitionCriteria(
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
        valid_hash = temp.cryptographic_hash

        instance = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100.00"),
            allocated_price={},
            performance_satisfied=True,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=["delivery_note"],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
            progress_percentage=Decimal("100.00"),
            cryptographic_hash=valid_hash,
        )
        assert instance.cryptographic_hash == valid_hash

    def test_construction_with_invalid_hash_raises(self):
        with pytest.raises(ValueError, match="Hash mismatch"):
            RevenueRecognitionCriteria(
                contract_identified=True,
                performance_obligations=["delivery"],
                transaction_price=Decimal("100.00"),
                allocated_price={},
                performance_satisfied=True,
                satisfaction_date=datetime.now(UTC),
                evidence_of_satisfaction=["delivery_note"],
                recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
                progress_percentage=Decimal("100.00"),
                cryptographic_hash="invalid_hash",
            )

    def test_is_ready_for_recognition(self):
        # All conditions met
        criteria = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100"),
            allocated_price={},
            performance_satisfied=True,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=["delivery_note"],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        )
        assert criteria.is_ready_for_recognition() is True

        # Missing evidence
        criteria2 = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100"),
            allocated_price={},
            performance_satisfied=True,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=[],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        )
        assert criteria2.is_ready_for_recognition() is False

        # Performance not satisfied
        criteria3 = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100"),
            allocated_price={},
            performance_satisfied=False,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=["delivery_note"],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        )
        assert criteria3.is_ready_for_recognition() is False

    def test_get_recognizable_amount(self):
        # At a point in time, ready -> full amount
        criteria = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100"),
            allocated_price={},
            performance_satisfied=True,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=["delivery_note"],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        )
        assert criteria.get_recognizable_amount() == Decimal("100")

        # Over time with progress
        criteria2 = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["service"],
            transaction_price=Decimal("1000"),
            allocated_price={},
            performance_satisfied=True,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=["progress_report"],
            recognition_model=RevenueRecognitionModel.OVER_TIME,
            progress_percentage=Decimal("30"),
        )
        assert criteria2.get_recognizable_amount() == Decimal("300")

        # Not ready -> 0
        criteria3 = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100"),
            allocated_price={},
            performance_satisfied=False,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=[],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        )
        assert criteria3.get_recognizable_amount() == Decimal(0)


class TestExpenseRecognitionCriteria:
    def test_construction_success(self):
        instance = ExpenseRecognitionCriteria(
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
        assert isinstance(instance, ExpenseRecognitionCriteria)
        assert instance.economic_benefit_consumed is True
        assert instance.liability_incurred is True
        assert instance.matching_method == ExpenseMatchingMethod.DIRECT_MATCHING
        assert instance.cryptographic_hash != ""

    def test_construction_with_valid_hash(self):
        temp = ExpenseRecognitionCriteria(
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
        valid_hash = temp.cryptographic_hash

        instance = ExpenseRecognitionCriteria(
            economic_benefit_consumed=True,
            liability_incurred=True,
            recognition_date=datetime.now(UTC),
            supporting_document="invoice_123",
            matching_revenue_id=uuid4(),
            matching_method=ExpenseMatchingMethod.DIRECT_MATCHING,
            is_allocated=True,
            allocation_method="straight-line",
            allocation_periods=12,
            cryptographic_hash=valid_hash,
        )
        assert instance.cryptographic_hash == valid_hash

    def test_construction_with_invalid_hash_raises(self):
        with pytest.raises(ValueError, match="Hash mismatch"):
            ExpenseRecognitionCriteria(
                economic_benefit_consumed=True,
                liability_incurred=True,
                recognition_date=datetime.now(UTC),
                supporting_document="invoice_123",
                matching_revenue_id=uuid4(),
                matching_method=ExpenseMatchingMethod.DIRECT_MATCHING,
                is_allocated=True,
                allocation_method="straight-line",
                allocation_periods=12,
                cryptographic_hash="invalid_hash",
            )

    def test_is_ready_for_recognition(self):
        criteria = ExpenseRecognitionCriteria(
            economic_benefit_consumed=True,
            liability_incurred=False,
            recognition_date=datetime.now(UTC),
            supporting_document="inv",
        )
        assert criteria.is_ready_for_recognition() is True

        criteria2 = ExpenseRecognitionCriteria(
            economic_benefit_consumed=False,
            liability_incurred=True,
            recognition_date=datetime.now(UTC),
            supporting_document="inv",
        )
        assert criteria2.is_ready_for_recognition() is True

        criteria3 = ExpenseRecognitionCriteria(
            economic_benefit_consumed=False,
            liability_incurred=False,
            recognition_date=datetime.now(UTC),
            supporting_document="inv",
        )
        assert criteria3.is_ready_for_recognition() is False


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
        }
        instance = AccrualEntry(**kwargs)
        assert isinstance(instance, AccrualEntry)
        assert instance.accrual_id == accrual_id
        assert instance.accrual_type == AccrualType.ACCRUED_REVENUE
        assert instance.amount == Decimal("100.00")
        assert instance.journal_entry_id == journal_id
        assert instance.reversed is False
        assert instance.cryptographic_hash != ""

    def test_validate_amount_positive(self):
        with pytest.raises(ValueError, match="Amount must be positive"):
            AccrualEntry(
                accrual_id=uuid4(),
                accrual_type=AccrualType.ACCRUED_REVENUE,
                amount=Decimal("-10"),
                currency="IDR",
                recognition_date=datetime.now(UTC),
                reversal_date=None,
                journal_entry_id=None,
                description="Test",
                created_by="tester",
                created_at=datetime.now(UTC),
                approved_by=["approver"],
                version=1,
            )

    def test_validate_at_least_one_approver(self):
        with pytest.raises(ValueError, match="At least one approver required"):
            AccrualEntry(
                accrual_id=uuid4(),
                accrual_type=AccrualType.ACCRUED_REVENUE,
                amount=Decimal("100"),
                currency="IDR",
                recognition_date=datetime.now(UTC),
                reversal_date=None,
                journal_entry_id=None,
                description="Test",
                created_by="tester",
                created_at=datetime.now(UTC),
                approved_by=[],
                version=1,
            )

    def test_mark_reversed(self):
        entry = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        new_entry = entry.mark_reversed(reversed_by="admin", journal_entry_id=uuid4())
        assert new_entry.reversed is True
        assert new_entry.reversed_by == "admin"
        assert new_entry.reversed_at is not None
        assert new_entry.journal_entry_id is not None
        assert new_entry.version == 2
        assert new_entry._audit_trail[-1]["action"] == "REVERSE"

    def test_mark_reversed_already_reversed(self):
        entry = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            reversed=True,
            version=1,
        )
        with pytest.raises(ValueError, match="Accrual already reversed"):
            entry.mark_reversed("admin")

    def test_is_active(self):
        entry = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=datetime.now(UTC) + timedelta(days=10),
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        # Active: not reversed, reversal_date in future, not deleted
        assert entry.is_active() is True
        # Reversed -> inactive
        entry_reversed = entry.mark_reversed("admin")
        assert entry_reversed.is_active() is False
        # Reversal date passed -> inactive
        entry2 = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=datetime.now(UTC) - timedelta(days=1),
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        assert entry2.is_active() is False


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
        with patch.object(AccrualBasisValidator, 'validate_revenue_recognition', return_value=(True, None, None)) as mock_method:
            is_valid, violation, msg = AccrualBasisValidator.validate_revenue_recognition(
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
            assert msg is None

    def test_validate_revenue_recognition_invalid(self):
        with patch.object(AccrualBasisValidator, 'validate_revenue_recognition', return_value=(False, "Violation", "criteria not met")) as mock_method:
            is_valid, violation, msg = AccrualBasisValidator.validate_revenue_recognition(
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
            assert msg == "criteria not met"

    def test_validate_expense_recognition_valid(self):
        with patch.object(AccrualBasisValidator, 'validate_expense_recognition', return_value=(True, None, None)) as mock_method:
            is_valid, violation, msg = AccrualBasisValidator.validate_expense_recognition(
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
            assert msg is None

    def test_validate_expense_recognition_invalid(self):
        with patch.object(AccrualBasisValidator, 'validate_expense_recognition', return_value=(False, "Violation", "criteria not met")) as mock_method:
            is_valid, violation, msg = AccrualBasisValidator.validate_expense_recognition(
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
            assert msg == "criteria not met"

    def test_determine_severity_by_days(self):
        # Test each severity level based on days
        assert AccrualBasisValidator._determine_severity_by_days(95) == AccrualBasisSeverity.CATASTROPHIC
        assert AccrualBasisValidator._determine_severity_by_days(45) == AccrualBasisSeverity.CRITICAL
        assert AccrualBasisValidator._determine_severity_by_days(20) == AccrualBasisSeverity.HIGH
        assert AccrualBasisValidator._determine_severity_by_days(10) == AccrualBasisSeverity.MEDIUM
        assert AccrualBasisValidator._determine_severity_by_days(3) == AccrualBasisSeverity.LOW
        assert AccrualBasisValidator._determine_severity_by_days(1) == AccrualBasisSeverity.INFO
        assert AccrualBasisValidator._determine_severity_by_days(0) == AccrualBasisSeverity.INFO

    def test_create_violation(self):
        now = datetime.now(UTC)
        violation = AccrualBasisValidator._create_violation(
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=now,
            recognition_date=now + timedelta(days=5),
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="Test",
            is_auto_corrected=False,
            detected_by="system",
        )
        assert isinstance(violation, AccrualBasisViolation)
        assert violation.difference_days == 5
        assert violation.severity == AccrualBasisSeverity.HIGH


# ============================================================================
# TESTS FOR AXIOM
# ============================================================================

class TestAccrualBasisAxiom:
    def test_construction(self):
        instance = AccrualBasisAxiom()
        assert isinstance(instance, AccrualBasisAxiom)

    def test_save_accrual_success(self):
        axiom = AccrualBasisAxiom()
        accrual = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        axiom.save_accrual(accrual)
        assert len(axiom._accruals) == 1
        assert axiom._accruals[accrual.accrual_id] is accrual

    def test_get_accrual_found(self):
        axiom = AccrualBasisAxiom()
        accrual_id = uuid4()
        mock_accrual = AccrualEntry(
            accrual_id=accrual_id,
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
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
        accrual1 = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test1",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        accrual2 = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_EXPENSE,
            amount=Decimal("200"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test2",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
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
        axiom._accruals[accrual_id] = AccrualEntry(
            accrual_id=accrual_id,
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        result = axiom.delete_accrual(accrual_id)
        assert result is True
        assert accrual_id not in axiom._accruals

    def test_delete_accrual_not_found(self):
        axiom = AccrualBasisAxiom()
        result = axiom.delete_accrual(uuid4())
        assert result is False

    def test_save_violation(self):
        axiom = AccrualBasisAxiom()
        violation = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="Test",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        axiom.save_violation(violation)
        assert len(axiom._violations) == 1
        assert axiom._violations[0] is violation

    def test_get_violations(self):
        axiom = AccrualBasisAxiom()
        v1 = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="v1",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        v2 = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="EXPENSE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.LOW,
            message="v2",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by="admin",
            correction_journal_id=uuid4(),
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        axiom._violations = [v1, v2]
        # All
        result = axiom.get_violations(limit=10)
        assert len(result) == 2
        # Filter by severity
        result2 = axiom.get_violations(min_severity=AccrualBasisSeverity.MEDIUM)
        assert len(result2) == 1
        assert result2[0] is v1
        # Unresolved only
        result3 = axiom.get_violations(unresolved_only=True)
        assert len(result3) == 1
        assert result3[0] is v1

    def test_resolve_violation(self):
        axiom = AccrualBasisAxiom()
        violation = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="Test",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        axiom.save_violation(violation)
        journal_id = uuid4()
        resolved = axiom.resolve_violation(violation.violation_id, "admin", journal_id)
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"
        assert resolved.correction_journal_id == journal_id
        assert resolved.version == 2

    def test_resolve_violation_not_found(self):
        axiom = AccrualBasisAxiom()
        # no violation
        result = axiom.resolve_violation(uuid4(), "admin", uuid4())
        assert result is None

    def test_enforce_revenue_recognition(self):
        axiom = AccrualBasisAxiom()
        criteria = RevenueRecognitionCriteria(
            contract_identified=True,
            performance_obligations=["delivery"],
            transaction_price=Decimal("100"),
            allocated_price={},
            performance_satisfied=True,
            satisfaction_date=datetime.now(UTC),
            evidence_of_satisfaction=["delivery_note"],
            recognition_model=RevenueRecognitionModel.AT_A_POINT_IN_TIME,
        )
        is_valid, violation, msg = axiom.enforce_revenue_recognition(
            transaction_id=uuid4(),
            cash_receipt_date=datetime.now(UTC),
            service_delivery_date=datetime.now(UTC),
            contract_criteria=criteria,
            amount=Decimal("100"),
            tolerance_days=7,
        )
        # With same dates, should be valid
        assert is_valid is True
        assert violation is None
        assert msg is None

    def test_enforce_expense_recognition(self):
        axiom = AccrualBasisAxiom()
        criteria = ExpenseRecognitionCriteria(
            economic_benefit_consumed=True,
            liability_incurred=True,
            recognition_date=datetime.now(UTC),
            supporting_document="inv",
            matching_method=ExpenseMatchingMethod.IMMEDIATE_RECOGNITION,
        )
        is_valid, violation, msg = axiom.enforce_expense_recognition(
            transaction_id=uuid4(),
            cash_payment_date=datetime.now(UTC),
            expense_incurred_date=datetime.now(UTC),
            expense_criteria=criteria,
            amount=Decimal("100"),
            tolerance_days=7,
        )
        assert is_valid is True
        assert violation is None
        assert msg is None

    def test_create_accrual(self):
        axiom = AccrualBasisAxiom()
        accrual = axiom.create_accrual(
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=datetime.now(UTC) + timedelta(days=30),
            description="Test",
            created_by="tester",
            approved_by=["approver1", "approver2"],
            journal_entry_id=uuid4(),
        )
        assert isinstance(accrual, AccrualEntry)
        assert accrual.accrual_type == AccrualType.ACCRUED_REVENUE
        assert accrual.amount == Decimal("100")
        assert accrual.currency == "IDR"
        assert accrual.approved_by == ["approver1", "approver2"]
        assert accrual.version == 1
        # Should be saved
        assert accrual.accrual_id in axiom._accruals

    def test_create_accrual_invalid_amount(self):
        axiom = AccrualBasisAxiom()
        with pytest.raises(ValueError, match="Amount must be positive"):
            axiom.create_accrual(
                accrual_type=AccrualType.ACCRUED_REVENUE,
                amount=Decimal("-10"),
                currency="IDR",
                recognition_date=datetime.now(UTC),
                reversal_date=None,
                description="Test",
                created_by="tester",
                approved_by=["approver"],
            )

    def test_create_accrual_no_approver(self):
        axiom = AccrualBasisAxiom()
        with pytest.raises(ValueError, match="At least one approver required"):
            axiom.create_accrual(
                accrual_type=AccrualType.ACCRUED_REVENUE,
                amount=Decimal("100"),
                currency="IDR",
                recognition_date=datetime.now(UTC),
                reversal_date=None,
                description="Test",
                created_by="tester",
                approved_by=[],
            )

    def test_get_statistics(self):
        axiom = AccrualBasisAxiom()
        # Add some accruals and violations
        accrual1 = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        accrual2 = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_EXPENSE,
            amount=Decimal("50"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test2",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        axiom.save_accrual(accrual1)
        axiom.save_accrual(accrual2)
        # Make one active, one not (reversed)
        accrual2_reversed = accrual2.mark_reversed("admin")
        axiom.save_accrual(accrual2_reversed)

        violation = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="Test",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        axiom.save_violation(violation)

        stats = axiom.get_statistics()
        assert stats["total_accruals"] == 2
        # active_accruals: accrual1 active, accrual2_reversed not active
        assert stats["active_accruals"] == 1
        assert stats["total_violations"] == 1
        assert stats["unresolved_violations"] == 1
        assert stats["severity_breakdown"]["HIGH"] == 1

    def test_reset(self):
        axiom = AccrualBasisAxiom()
        # Add some data
        accrual = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        axiom.save_accrual(accrual)
        axiom.reset()
        assert len(axiom._accruals) == 0
        assert len(axiom._violations) == 0
        assert len(axiom._revenue_criteria_cache) == 0
        assert len(axiom._expense_criteria_cache) == 0


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
    with patch.object(AccrualBasisValidator, 'validate_revenue_recognition', return_value=(True, None, None)):
        is_valid, violation, msg = enforce_revenue_recognition(
            transaction_id=uuid4(),
            cash_receipt_date=datetime.now(UTC),
            service_delivery_date=datetime.now(UTC),
            contract_criteria=MagicMock(),
            amount=Decimal("100.00"),
            tolerance_days=1,
        )
        assert is_valid is True
        assert violation is None
        assert msg is None


def test_enforce_expense_recognition_returns_tuple():
    with patch.object(AccrualBasisValidator, 'validate_expense_recognition', return_value=(True, None, None)):
        is_valid, violation, msg = enforce_expense_recognition(
            transaction_id=uuid4(),
            cash_payment_date=datetime.now(UTC),
            expense_incurred_date=datetime.now(UTC),
            expense_criteria=MagicMock(),
            amount=Decimal("100.00"),
            tolerance_days=1,
        )
        assert is_valid is True
        assert violation is None
        assert msg is None


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
    stats = get_statistics()
    assert isinstance(stats, dict)
    assert "total_accruals" in stats
    assert "active_accruals" in stats
    assert "total_violations" in stats
    assert "unresolved_violations" in stats


def test_reset_clears_state():
    axiom = get_accrual_basis_axiom()
    accrual = create_accrual(
        accrual_type=AccrualType.ACCRUED_REVENUE,
        amount=Decimal("100.00"),
        currency="IDR",
        recognition_date=datetime.now(UTC),
        reversal_date=datetime.now(UTC),
        description="Test",
        created_by="tester",
        approved_by=["approver"],
        journal_entry_id=uuid4(),
    )
    axiom.save_accrual(accrual)
    assert len(axiom.get_all_accruals()) == 1

    reset()
    assert len(axiom.get_all_accruals()) == 0


# ============================================================================
# ADDITIONAL COVERAGE TESTS
# ============================================================================

class TestAdditionalCoverage:
    def test_accrual_entry_entity_methods(self):
        entry = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=AccrualType.ACCRUED_REVENUE,
            amount=Decimal("100"),
            currency="IDR",
            recognition_date=datetime.now(UTC),
            reversal_date=None,
            journal_entry_id=None,
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["approver"],
            version=1,
        )
        # create method (no-op, just returns self)
        result = entry.create("tester")
        assert result is entry
        # activate/deactivate (no-op)
        result2 = entry.activate("tester")
        assert result2 is entry
        result3 = entry.deactivate("tester", "reason")
        assert result3 is entry
        # lock/unlock (no-op)
        result4 = entry.lock("tester", "reason")
        assert result4 is entry
        result5 = entry.unlock("tester")
        assert result5 is entry
        # update
        updated = entry.update("admin", description="Updated")
        assert updated.description == "Updated"
        assert updated.version == 2
        # delete
        deleted = updated.delete("admin", "reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == 3
        # restore
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == 4
        # clone
        cloned = restored.clone()
        assert cloned.accrual_id != restored.accrual_id
        assert cloned.version == 1
        assert cloned.reversed is False
        assert cloned.deleted_at is None
        # snapshot
        snap = restored.snapshot()
        assert snap["accrual_id"] == str(restored.accrual_id)
        assert snap["version"] == 4
        # audit_trail
        trail = restored.audit_trail()
        assert len(trail) > 0
        # touch
        touched = restored.touch("admin")
        assert touched.version == 5
        # get_version
        assert touched.get_version() == 5
        # validate
        val_result = touched.validate()
        assert val_result["is_valid"] is True

    def test_violation_entity_methods(self):
        violation = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="Test",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        # create (no-op)
        result = violation.create("system")
        assert result is violation
        # activate/deactivate (no-op)
        result2 = violation.activate("system")
        assert result2 is violation
        result3 = violation.deactivate("system", "reason")
        assert result3 is violation
        # lock/unlock (no-op)
        result4 = violation.lock("system", "reason")
        assert result4 is violation
        result5 = violation.unlock("system")
        assert result5 is violation
        # update raises AttributeError
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")
        # delete raises AttributeError
        with pytest.raises(AttributeError):
            violation.delete("admin")
        # restore raises AttributeError
        with pytest.raises(AttributeError):
            violation.restore("admin")
        # clone
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.version == 1
        assert cloned.resolved is False
        # snapshot
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        # audit_trail
        trail = violation.audit_trail()
        assert len(trail) > 0
        # touch
        touched = violation.touch("admin")
        assert touched is violation
        # get_version
        assert touched.get_version() == 1
        # validate
        val_result = violation.validate()
        assert val_result["is_valid"] is True

    def test_violation_resolve(self):
        violation = AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=uuid4(),
            transaction_type="REVENUE",
            cash_flow_date=datetime.now(UTC),
            recognition_date=datetime.now(UTC),
            difference_days=0,
            amount=Decimal("100"),
            severity=AccrualBasisSeverity.HIGH,
            message="Test",
            detected_at=datetime.now(UTC),
            detected_by="system",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=False,
            auto_correction_applied=None,
            version=1,
        )
        journal_id = uuid4()
        resolved = violation.resolve("admin", journal_id)
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"
        assert resolved.correction_journal_id == journal_id
        assert resolved.version == 2
        # Can't resolve again
        with pytest.raises(ValueError, match="Violation already resolved"):
            resolved.resolve("admin", uuid4())
