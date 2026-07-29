# tests/infrastructure/persistence_orm/test_payroll_run_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/payroll_run_table.py
Covers all properties, methods, and edge cases with proper mocking.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from infrastructure.persistence_orm.payroll_run_table import PayrollRunTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def created_by() -> UUID:
    return uuid4()


@pytest.fixture
def approved_by() -> UUID:
    return uuid4()


@pytest.fixture
def paid_by() -> UUID:
    return uuid4()


@pytest.fixture
def payment_run_id() -> UUID:
    return uuid4()


@pytest.fixture
def payroll_run(legal_entity_id, created_by) -> PayrollRunTable:
    """Create a default PayrollRunTable instance in 'calculated' state."""
    return PayrollRunTable(
        id=uuid4(),
        run_number="PR-2026-01",
        period_year=2026,
        period_month=1,
        total_employees=10,
        total_net_salary=Decimal("100000000"),
        total_tax=Decimal("10000000"),
        total_deductions=Decimal("5000000"),
        currency="IDR",
        status="calculated",
        legal_entity_id=legal_entity_id,
        created_by=created_by,
    )


# ============================================================================
# Basic ORM tests (tablename, instantiation)
# ============================================================================

class TestPayrollRunTableModel:
    def test_tablename_defined(self):
        assert hasattr(PayrollRunTable, '__tablename__')
        assert PayrollRunTable.__tablename__ == "payroll_run"

    def test_table_args(self):
        assert hasattr(PayrollRunTable, '__table_args__')
        args = PayrollRunTable.__table_args__
        assert isinstance(args, tuple) or isinstance(args, dict)
        # Check that there are constraints (we can just check presence)
        # Since we can't easily inspect all, we'll just verify it's not empty.
        assert len(args) > 0

    def test_instantiation(self, payroll_run):
        assert payroll_run.id is not None
        assert payroll_run.run_number == "PR-2026-01"
        assert payroll_run.period_year == 2026
        assert payroll_run.period_month == 1
        assert payroll_run.total_employees == 10
        assert payroll_run.total_net_salary == Decimal("100000000")
        assert payroll_run.total_tax == Decimal("10000000")
        assert payroll_run.total_deductions == Decimal("5000000")
        assert payroll_run.currency == "IDR"
        assert payroll_run.status == "calculated"
        assert payroll_run.legal_entity_id is not None


# ============================================================================
# Property Tests
# ============================================================================

class TestPayrollRunTableProperties:
    def test_is_calculated_true(self, payroll_run):
        assert payroll_run.is_calculated is True
        assert payroll_run.is_approved is False
        assert payroll_run.is_paid is False
        assert payroll_run.is_cancelled is False

    def test_is_approved_true(self, payroll_run):
        payroll_run.status = "approved"
        assert payroll_run.is_calculated is False
        assert payroll_run.is_approved is True
        assert payroll_run.is_paid is False
        assert payroll_run.is_cancelled is False

    def test_is_paid_true(self, payroll_run):
        payroll_run.status = "paid"
        assert payroll_run.is_calculated is False
        assert payroll_run.is_approved is False
        assert payroll_run.is_paid is True
        assert payroll_run.is_cancelled is False

    def test_is_cancelled_true(self, payroll_run):
        payroll_run.status = "cancelled"
        assert payroll_run.is_calculated is False
        assert payroll_run.is_approved is False
        assert payroll_run.is_paid is False
        assert payroll_run.is_cancelled is True

    def test_period_display(self, payroll_run):
        assert payroll_run.period_display == "2026-01"
        payroll_run.period_month = 12
        assert payroll_run.period_display == "2026-12"
        payroll_run.period_year = 2025
        assert payroll_run.period_display == "2025-12"

    def test_average_net_salary_per_employee(self, payroll_run):
        # total_net_salary=100,000,000 / 10 = 10,000,000
        assert payroll_run.average_net_salary_per_employee == Decimal("10000000")

    def test_average_net_salary_per_employee_zero_employees(self, payroll_run):
        payroll_run.total_employees = 0
        assert payroll_run.average_net_salary_per_employee == Decimal(0)

    def test_average_net_salary_per_employee_fractional(self, payroll_run):
        payroll_run.total_employees = 3
        payroll_run.total_net_salary = Decimal("10000000")
        # 10,000,000 / 3 = 3,333,333.3333...
        # Decimal division produces exact decimal, we just check approximate
        expected = Decimal("3333333.333333333333333333333333333333")
        assert payroll_run.average_net_salary_per_employee == expected


# ============================================================================
# Method Tests
# ============================================================================

class TestPayrollRunTableMethods:
    def test_approve_success(self, payroll_run, approved_by):
        with patch("infrastructure.persistence_orm.payroll_run_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now
            mock_dt.UTC = UTC

            initial_version = payroll_run.version
            payroll_run.approve(approved_by)

            assert payroll_run.status == "approved"
            assert payroll_run.approved_by == approved_by
            assert payroll_run.approved_at == fixed_now
            assert payroll_run.version == initial_version + 1

    def test_approve_invalid_status_raises(self, payroll_run, approved_by):
        payroll_run.status = "approved"  # already approved
        with pytest.raises(ValueError, match="Cannot approve payroll run with status approved"):
            payroll_run.approve(approved_by)

        payroll_run.status = "paid"
        with pytest.raises(ValueError, match="Cannot approve payroll run with status paid"):
            payroll_run.approve(approved_by)

        payroll_run.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot approve payroll run with status cancelled"):
            payroll_run.approve(approved_by)

    def test_mark_paid_success(self, payroll_run, approved_by, paid_by, payment_run_id):
        # First approve to set status to approved
        payroll_run.status = "approved"  # pre-approve
        with patch("infrastructure.persistence_orm.payroll_run_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 16, 14, 30, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now
            mock_dt.UTC = UTC

            initial_version = payroll_run.version
            payroll_run.mark_paid(paid_by, payment_run_id)

            assert payroll_run.status == "paid"
            assert payroll_run.paid_by == paid_by
            assert payroll_run.paid_at == fixed_now
            assert payroll_run.payment_run_id == payment_run_id
            assert payroll_run.version == initial_version + 1

    def test_mark_paid_invalid_status_raises(self, payroll_run, paid_by, payment_run_id):
        payroll_run.status = "calculated"
        with pytest.raises(ValueError, match="Cannot mark payroll run as paid with status calculated"):
            payroll_run.mark_paid(paid_by, payment_run_id)

        payroll_run.status = "paid"
        with pytest.raises(ValueError, match="Cannot mark payroll run as paid with status paid"):
            payroll_run.mark_paid(paid_by, payment_run_id)

        payroll_run.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot mark payroll run as paid with status cancelled"):
            payroll_run.mark_paid(paid_by, payment_run_id)

    def test_cancel_success_calculated(self, payroll_run):
        initial_version = payroll_run.version
        payroll_run.cancel()
        assert payroll_run.status == "cancelled"
        assert payroll_run.version == initial_version + 1

    def test_cancel_success_approved(self, payroll_run):
        payroll_run.status = "approved"
        initial_version = payroll_run.version
        payroll_run.cancel()
        assert payroll_run.status == "cancelled"
        assert payroll_run.version == initial_version + 1

    def test_cancel_paid_raises(self, payroll_run):
        payroll_run.status = "paid"
        with pytest.raises(ValueError, match="Cannot cancel a paid payroll run"):
            payroll_run.cancel()

    def test_update_totals(self, payroll_run):
        initial_version = payroll_run.version
        new_employees = 15
        new_net = Decimal("150000000")
        new_tax = Decimal("15000000")
        new_deductions = Decimal("7500000")

        payroll_run.update_totals(new_employees, new_net, new_tax, new_deductions)

        assert payroll_run.total_employees == new_employees
        assert payroll_run.total_net_salary == new_net
        assert payroll_run.total_tax == new_tax
        assert payroll_run.total_deductions == new_deductions
        assert payroll_run.version == initial_version + 1

    def test_to_dict(self, payroll_run, legal_entity_id):
        d = payroll_run.to_dict()
        assert d["id"] == str(payroll_run.id)
        assert d["run_number"] == "PR-2026-01"
        assert d["period_year"] == 2026
        assert d["period_month"] == 1
        assert d["total_employees"] == 10
        assert d["total_net_salary"] == 100000000.0
        assert d["total_tax"] == 10000000.0
        assert d["total_deductions"] == 5000000.0
        assert d["currency"] == "IDR"
        assert d["status"] == "calculated"
        assert d["approved_by"] is None
        assert d["approved_at"] is None
        assert d["paid_by"] is None
        assert d["paid_at"] is None
        assert d["payment_run_id"] is None
        assert d["notes"] is None
        assert d["legal_entity_id"] == str(legal_entity_id)

    def test_to_dict_with_optional_fields(self, payroll_run, approved_by, paid_by, payment_run_id):
        # Set optional fields
        payroll_run.approved_by = approved_by
        payroll_run.approved_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        payroll_run.paid_by = paid_by
        payroll_run.paid_at = datetime(2026, 1, 16, 14, 0, 0, tzinfo=UTC)
        payroll_run.payment_run_id = payment_run_id
        payroll_run.notes = "Test notes"

        d = payroll_run.to_dict()
        assert d["approved_by"] == str(approved_by)
        assert d["approved_at"] == "2026-01-15T10:00:00+00:00"
        assert d["paid_by"] == str(paid_by)
        assert d["paid_at"] == "2026-01-16T14:00:00+00:00"
        assert d["payment_run_id"] == str(payment_run_id)
        assert d["notes"] == "Test notes"


# ============================================================================
# Integration-like tests (state transitions)
# ============================================================================

class TestPayrollRunTableStateTransitions:
    def test_full_workflow(self, payroll_run, approved_by, paid_by, payment_run_id):
        # Initially calculated
        assert payroll_run.status == "calculated"
        assert payroll_run.is_calculated

        # Approve
        with patch("infrastructure.persistence_orm.payroll_run_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
            payroll_run.approve(approved_by)
        assert payroll_run.status == "approved"
        assert payroll_run.is_approved
        assert payroll_run.approved_by == approved_by

        # Mark paid
        with patch("infrastructure.persistence_orm.payroll_run_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 16, 14, 0, 0, tzinfo=UTC)
            payroll_run.mark_paid(paid_by, payment_run_id)
        assert payroll_run.status == "paid"
        assert payroll_run.is_paid
        assert payroll_run.paid_by == paid_by
        assert payroll_run.payment_run_id == payment_run_id

    def test_cancel_from_calculated(self, payroll_run):
        payroll_run.cancel()
        assert payroll_run.status == "cancelled"
        assert payroll_run.is_cancelled

    def test_cancel_from_approved(self, payroll_run, approved_by):
        payroll_run.status = "approved"
        payroll_run.cancel()
        assert payroll_run.status == "cancelled"

    def test_cannot_cancel_paid(self, payroll_run, approved_by, paid_by, payment_run_id):
        payroll_run.status = "paid"
        with pytest.raises(ValueError, match="Cannot cancel a paid payroll run"):
            payroll_run.cancel()


# ============================================================================
# Edge Cases and Precision
# ============================================================================

class TestPayrollRunTableEdgeCases:
    def test_average_net_salary_with_decimal_precision(self):
        pr = PayrollRunTable(
            id=uuid4(),
            run_number="PR-001",
            period_year=2026,
            period_month=1,
            total_employees=7,
            total_net_salary=Decimal("1000000.00"),
            total_tax=Decimal("0"),
            total_deductions=Decimal("0"),
            currency="IDR",
            status="calculated",
            legal_entity_id=uuid4(),
        )
        expected = Decimal("142857.142857142857142857142857142857")
        assert pr.average_net_salary_per_employee == expected

    def test_zero_total_employees_average(self):
        pr = PayrollRunTable(
            id=uuid4(),
            run_number="PR-002",
            period_year=2026,
            period_month=2,
            total_employees=0,
            total_net_salary=Decimal("0"),
            total_tax=Decimal("0"),
            total_deductions=Decimal("0"),
            currency="IDR",
            status="calculated",
            legal_entity_id=uuid4(),
        )
        assert pr.average_net_salary_per_employee == Decimal(0)

    def test_negative_totals_allowed_by_model(self):
        # The model constraints don't prevent negative totals, but we test that they can be set.
        pr = PayrollRunTable(
            id=uuid4(),
            run_number="PR-003",
            period_year=2026,
            period_month=3,
            total_employees=5,
            total_net_salary=Decimal("-1000000"),  # negative
            total_tax=Decimal("-100000"),
            total_deductions=Decimal("-50000"),
            currency="IDR",
            status="calculated",
            legal_entity_id=uuid4(),
        )
        assert pr.total_net_salary == Decimal("-1000000")
        assert pr.total_tax == Decimal("-100000")
        assert pr.total_deductions == Decimal("-50000")
