# test_payroll_run_entity.py
# Comprehensive tests for payroll_run_entity.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.payroll.payroll_run_entity import (
    PayrollEmployeeResult,
    PayrollPeriod,
    PayrollRunEntity,
    PayrollRunRepository,
    PayrollRunStatus,
)
from domain.payroll.salary_component_entity import ComponentType, SalaryComponentEntity


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_salary_component():
    """Create a valid SalaryComponentEntity."""
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Basic Salary",
        component_type=ComponentType.BASIC,
        amount=Decimal("5000000"),
        currency="IDR",
        frequency=ComponentFrequency.MONTHLY,
        description="Monthly basic",
        is_taxable=True,
        is_mandatory=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by="system",
        version=1,
    )


@pytest.fixture
def allowance_component():
    """Create an allowance component."""
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Transport Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("500000"),
        currency="IDR",
        frequency=ComponentFrequency.MONTHLY,
        description="Transport",
        is_taxable=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by="system",
        version=1,
    )


@pytest.fixture
def deduction_component():
    """Create a deduction component."""
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Health Insurance",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("-200000"),
        currency="IDR",
        frequency=ComponentFrequency.MONTHLY,
        description="Health premium",
        is_taxable=False,
        is_mandatory=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by="system",
        version=1,
    )


@pytest.fixture
def valid_employee_result(valid_salary_component, allowance_component, deduction_component):
    """Create a valid PayrollEmployeeResult."""
    return PayrollEmployeeResult(
        employee_id=uuid4(),
        employee_name="John Doe",
        gross_salary=Decimal("5000000"),
        allowances=Decimal("500000"),
        deductions=Decimal("200000"),
        tax=Decimal("300000"),
        net_salary=Decimal("5000000"),  # simplified
        components=[valid_salary_component, allowance_component, deduction_component],
        bank_account_number="1234567890",
        payment_reference="PAY-001",
        paid_at=None,
    )


@pytest.fixture
def another_employee_result():
    """Another employee result."""
    return PayrollEmployeeResult(
        employee_id=uuid4(),
        employee_name="Jane Smith",
        gross_salary=Decimal("8000000"),
        allowances=Decimal("1000000"),
        deductions=Decimal("300000"),
        tax=Decimal("500000"),
        net_salary=Decimal("8200000"),
        components=[],
        bank_account_number="0987654321",
    )


@pytest.fixture
def payroll_run(valid_employee_result):
    """Create a payroll run in DRAFT status with one employee."""
    run = PayrollRunEntity.create(
        run_number="PR-2025-01",
        period=PayrollPeriod.MONTHLY,
        created_by="system",
        period_year=2025,
        period_month=1,
    )
    # Add employee
    return run.add_employee(
        employee_id=valid_employee_result.employee_id,
        employee_name=valid_employee_result.employee_name,
        gross_salary=valid_employee_result.gross_salary,
        deductions=valid_employee_result.deductions,
        tax=valid_employee_result.tax,
        net_salary=valid_employee_result.net_salary,
        components=valid_employee_result.components,
        bank_account_number=valid_employee_result.bank_account_number,
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestPayrollRunStatus:
    def test_members(self):
        assert PayrollRunStatus.DRAFT.value == "draft"
        assert PayrollRunStatus.CALCULATED.value == "calculated"
        assert PayrollRunStatus.APPROVED.value == "approved"
        assert PayrollRunStatus.PAID.value == "paid"
        assert PayrollRunStatus.CANCELLED.value == "cancelled"


class TestPayrollPeriod:
    def test_members(self):
        assert PayrollPeriod.MONTHLY.value == "monthly"
        assert PayrollPeriod.SEMI_MONTHLY.value == "semi_monthly"
        assert PayrollPeriod.WEEKLY.value == "weekly"
        assert PayrollPeriod.DAILY.value == "daily"


# ============================================================================
# Tests for PayrollEmployeeResult
# ============================================================================

class TestPayrollEmployeeResult:
    def test_construction_valid(self, valid_employee_result):
        assert valid_employee_result.employee_name == "John Doe"
        assert valid_employee_result.gross_salary == Decimal("5000000")
        assert valid_employee_result.net_salary == Decimal("5000000")
        assert len(valid_employee_result.components) == 3

    def test_validation_gross_salary_negative(self):
        with pytest.raises(ValueError, match="Gross salary cannot be negative"):
            PayrollEmployeeResult(
                employee_id=uuid4(),
                employee_name="Test",
                gross_salary=Decimal("-100"),
                allowances=Decimal("0"),
                deductions=Decimal("0"),
                tax=Decimal("0"),
                net_salary=Decimal("0"),
            )

    def test_validation_deductions_negative(self):
        with pytest.raises(ValueError, match="Deductions cannot be negative"):
            PayrollEmployeeResult(
                employee_id=uuid4(),
                employee_name="Test",
                gross_salary=Decimal("100"),
                allowances=Decimal("0"),
                deductions=Decimal("-10"),
                tax=Decimal("0"),
                net_salary=Decimal("90"),
            )

    def test_validation_tax_negative(self):
        with pytest.raises(ValueError, match="Tax cannot be negative"):
            PayrollEmployeeResult(
                employee_id=uuid4(),
                employee_name="Test",
                gross_salary=Decimal("100"),
                allowances=Decimal("0"),
                deductions=Decimal("0"),
                tax=Decimal("-5"),
                net_salary=Decimal("95"),
            )

    def test_validation_net_salary_negative(self):
        with pytest.raises(ValueError, match="Net salary cannot be negative"):
            PayrollEmployeeResult(
                employee_id=uuid4(),
                employee_name="Test",
                gross_salary=Decimal("100"),
                allowances=Decimal("0"),
                deductions=Decimal("0"),
                tax=Decimal("0"),
                net_salary=Decimal("-10"),
            )

    def test_mark_paid(self, valid_employee_result):
        paid = valid_employee_result.mark_paid(
            payment_reference="PAY-002",
            paid_at=datetime(2025, 2, 1, 10, 0, 0, tzinfo=UTC),
        )
        assert paid.payment_reference == "PAY-002"
        assert paid.paid_at == datetime(2025, 2, 1, 10, 0, 0, tzinfo=UTC)
        # Other fields unchanged
        assert paid.employee_id == valid_employee_result.employee_id
        assert paid.gross_salary == valid_employee_result.gross_salary

    def test_to_dict(self, valid_employee_result):
        d = valid_employee_result.to_dict()
        assert d["employee_id"] == str(valid_employee_result.employee_id)
        assert d["employee_name"] == "John Doe"
        assert d["gross_salary"] == "5000000"
        assert d["allowances"] == "500000"
        assert d["deductions"] == "200000"
        assert d["tax"] == "300000"
        assert d["net_salary"] == "5000000"
        assert d["bank_account_number"] == "1234567890"
        assert d["payment_reference"] == "PAY-001"
        assert d["paid_at"] is None

    def test_to_payslip(self, valid_employee_result, payroll_run):
        # to_payslip requires a PayrollRunEntity. We'll use the payroll_run fixture.
        # It returns a PayslipProjection, which we can check basic attributes.
        payslip = valid_employee_result.to_payslip(payroll_run)
        assert payslip.employee_id == valid_employee_result.employee_id
        assert payslip.employee_name == valid_employee_result.employee_name
        assert payslip.gross_salary == valid_employee_result.gross_salary
        assert payslip.net_salary == valid_employee_result.net_salary
        assert payslip.tax == valid_employee_result.tax
        assert payslip.run_number == payroll_run.run_number
        assert payslip.period_month == payroll_run.period_month
        assert payslip.period_year == payroll_run.period_year


# ============================================================================
# Tests for PayrollRunEntity
# ============================================================================

class TestPayrollRunEntityConstruction:
    def test_create_defaults(self):
        run = PayrollRunEntity.create(
            run_number="PR-2025-01",
            period=PayrollPeriod.MONTHLY,
            created_by="system",
        )
        assert run.run_id is not None
        assert run.run_number == "PR-2025-01"
        assert run.period == PayrollPeriod.MONTHLY
        assert run.status == PayrollRunStatus.DRAFT
        assert run.employees == []
        assert run.total_gross == Decimal("0")
        assert run.total_net == Decimal("0")
        assert run.version == 1
        assert run.created_by == "system"
        # period_year/month should default to current year/month
        now = datetime.now(UTC)
        assert run.period_year == now.year
        assert run.period_month == now.month

    def test_create_with_explicit_period(self):
        run = PayrollRunEntity.create(
            run_number="PR-2025-01",
            period=PayrollPeriod.MONTHLY,
            created_by="system",
            period_year=2025,
            period_month=1,
        )
        assert run.period_year == 2025
        assert run.period_month == 1

    def test_validation_run_number_too_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            PayrollRunEntity(
                run_id=uuid4(),
                run_number="PR",
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=1,
                status=PayrollRunStatus.DRAFT,
            )

    def test_validation_version(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            PayrollRunEntity(
                run_id=uuid4(),
                run_number="PR-001",
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=1,
                status=PayrollRunStatus.DRAFT,
                version=0,
            )

    def test_validation_period_year_invalid(self):
        with pytest.raises(ValueError, match="Invalid period year"):
            PayrollRunEntity(
                run_id=uuid4(),
                run_number="PR-001",
                period=PayrollPeriod.MONTHLY,
                period_year=1999,
                period_month=1,
                status=PayrollRunStatus.DRAFT,
            )

    def test_validation_period_month_invalid(self):
        with pytest.raises(ValueError, match="Invalid period month"):
            PayrollRunEntity(
                run_id=uuid4(),
                run_number="PR-001",
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=13,
                status=PayrollRunStatus.DRAFT,
            )

    def test_validation_naive_timestamps(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            PayrollRunEntity(
                run_id=uuid4(),
                run_number="PR-001",
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=1,
                status=PayrollRunStatus.DRAFT,
                created_at=naive,
                updated_at=datetime.now(UTC),
            )


class TestPayrollRunEntityEmployeeManagement:
    def test_add_employee(self, payroll_run, valid_employee_result):
        old_count = len(payroll_run.employees)
        old_version = payroll_run.version
        # Add a second employee
        emp2 = PayrollEmployeeResult(
            employee_id=uuid4(),
            employee_name="Jane Doe",
            gross_salary=Decimal("6000000"),
            allowances=Decimal("0"),
            deductions=Decimal("0"),
            tax=Decimal("0"),
            net_salary=Decimal("6000000"),
            components=[],
        )
        new_run = payroll_run.add_employee(
            employee_id=emp2.employee_id,
            employee_name=emp2.employee_name,
            gross_salary=emp2.gross_salary,
            deductions=emp2.deductions,
            tax=emp2.tax,
            net_salary=emp2.net_salary,
            components=emp2.components,
            bank_account_number="",
        )
        assert len(new_run.employees) == old_count + 1
        assert new_run.employees[-1].employee_id == emp2.employee_id
        assert new_run.version == old_version + 1
        # Totals should not be recalculated until calculate()
        assert new_run.total_gross == Decimal("0")  # still zero

    def test_add_employee_update_existing(self, payroll_run, valid_employee_result):
        emp_id = valid_employee_result.employee_id
        old_count = len(payroll_run.employees)
        # Update with new values
        new_run = payroll_run.add_employee(
            employee_id=emp_id,
            employee_name="Updated Name",
            gross_salary=Decimal("7000000"),
            deductions=Decimal("100000"),
            tax=Decimal("200000"),
            net_salary=Decimal("6700000"),
            components=[],
            bank_account_number="999",
        )
        assert len(new_run.employees) == old_count  # replaced, not added
        updated_emp = new_run.get_employee_result(emp_id)
        assert updated_emp.employee_name == "Updated Name"
        assert updated_emp.gross_salary == Decimal("7000000")

    def test_get_employee_result(self, payroll_run, valid_employee_result):
        emp = payroll_run.get_employee_result(valid_employee_result.employee_id)
        assert emp == valid_employee_result
        assert payroll_run.get_employee_result(uuid4()) is None


class TestPayrollRunEntityStateTransitions:
    def test_calculate(self, payroll_run):
        # Initially DRAFT with no totals
        assert payroll_run.status == PayrollRunStatus.DRAFT
        assert payroll_run.total_gross == Decimal("0")
        assert payroll_run.total_net == Decimal("0")

        # Calculate
        calculated = payroll_run.calculate()
        assert calculated.status == PayrollRunStatus.CALCULATED
        assert calculated.calculated_at is not None
        assert calculated.calculated_by == payroll_run.created_by
        # Totals should be sum of employees
        # One employee: gross=5000000, deductions=200000, tax=300000, net=5000000? Actually net_salary is set to 5000000 but we need to ensure totals are correct.
        # In our fixture, net_salary=5000000, gross=5000000, deductions=200000, tax=300000 -> net should be 5000000? It's inconsistent but we test that totals are sums.
        total_gross = sum(e.gross_salary for e in calculated.employees)
        total_deductions = sum(e.deductions for e in calculated.employees)
        total_tax = sum(e.tax for e in calculated.employees)
        total_net = sum(e.net_salary for e in calculated.employees)
        assert calculated.total_gross == total_gross
        assert calculated.total_deductions == total_deductions
        assert calculated.total_tax == total_tax
        assert calculated.total_net == total_net
        assert calculated.version == payroll_run.version + 1

    def test_calculate_wrong_status(self, payroll_run):
        # First calculate
        calculated = payroll_run.calculate()
        # Try to calculate again
        with pytest.raises(ValueError, match="Cannot calculate payroll in status calculated"):
            calculated.calculate()

    def test_approve(self, payroll_run):
        # Must be calculated first
        calculated = payroll_run.calculate()
        approved = calculated.approve(approved_by="manager")
        assert approved.status == PayrollRunStatus.APPROVED
        assert approved.approved_at is not None
        assert approved.approved_by == "manager"
        assert approved.version == calculated.version + 1

    def test_approve_wrong_status(self, payroll_run):
        with pytest.raises(ValueError, match="Cannot approve payroll in status draft"):
            payroll_run.approve("manager")

    def test_process_payment(self, payroll_run):
        # Must be approved first
        calculated = payroll_run.calculate()
        approved = calculated.approve("manager")
        paid = approved.process_payment("finance")
        assert paid.status == PayrollRunStatus.PAID
        assert paid.paid_at is not None
        assert paid.paid_by == "finance"
        # Check each employee got payment reference and paid_at
        for emp in paid.employees:
            assert emp.payment_reference is not None
            assert emp.payment_reference.startswith("PAY-")
            assert emp.paid_at is not None
        assert paid.version == approved.version + 1

    def test_process_payment_wrong_status(self, payroll_run):
        with pytest.raises(ValueError, match="Cannot process payment in status draft"):
            payroll_run.process_payment("finance")

    def test_cancel_draft(self, payroll_run):
        cancelled = payroll_run.cancel(cancelled_by="admin", reason="Test cancel")
        assert cancelled.status == PayrollRunStatus.CANCELLED
        assert cancelled.version == payroll_run.version + 1
        assert cancelled.created_by == "admin"  # updated_by is set to cancelled_by

    def test_cancel_calculated(self, payroll_run):
        calculated = payroll_run.calculate()
        cancelled = calculated.cancel("admin", "Reason")
        assert cancelled.status == PayrollRunStatus.CANCELLED

    def test_cancel_approved(self, payroll_run):
        calculated = payroll_run.calculate()
        approved = calculated.approve("manager")
        cancelled = approved.cancel("admin", "Reason")
        assert cancelled.status == PayrollRunStatus.CANCELLED

    def test_cancel_paid_fails(self, payroll_run):
        calculated = payroll_run.calculate()
        approved = calculated.approve("manager")
        paid = approved.process_payment("finance")
        with pytest.raises(ValueError, match="Cannot cancel a paid payroll run"):
            paid.cancel("admin", "Reason")

    def test_cancel_already_cancelled_fails(self, payroll_run):
        cancelled = payroll_run.cancel("admin", "Reason")
        with pytest.raises(ValueError, match="already cancelled"):
            cancelled.cancel("admin", "Again")


class TestPayrollRunEntityUtility:
    def test_to_dict(self, payroll_run):
        d = payroll_run.to_dict()
        assert d["run_id"] == str(payroll_run.run_id)
        assert d["run_number"] == "PR-2025-01"
        assert d["period"] == "monthly"
        assert d["period_year"] == 2025
        assert d["period_month"] == 1
        assert d["status"] == "draft"
        assert d["employee_count"] == len(payroll_run.employees)
        assert d["total_gross"] == "0"
        assert d["total_net"] == "0"
        assert d["calculated_at"] is None
        assert d["approved_at"] is None
        assert d["paid_at"] is None
        assert d["version"] == payroll_run.version

    def test_to_dict_after_calculation(self, payroll_run):
        calculated = payroll_run.calculate()
        d = calculated.to_dict()
        assert d["status"] == "calculated"
        assert d["total_gross"] == str(calculated.total_gross)
        assert d["total_deductions"] == str(calculated.total_deductions)
        assert d["total_tax"] == str(calculated.total_tax)
        assert d["total_net"] == str(calculated.total_net)
        assert d["calculated_at"] is not None
        assert d["calculated_by"] == calculated.calculated_by


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestPayrollRunRepository:
    def test_abstract_methods_raise(self):
        repo = PayrollRunRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_period(uuid4(), 2025, 1)
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())