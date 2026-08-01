# test_payslip_projection.py
# Comprehensive tests for payslip_projection.py

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.payroll.payslip_projection import PayslipProjection, PayslipRepository
from domain.payroll.salary_component_entity import ComponentType, SalaryComponentEntity

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def allowance_component():
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Transport Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("500000"),
        currency="IDR",
        is_taxable=True,
        description="Monthly transport",
    )


@pytest.fixture
def deduction_component():
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Health Insurance",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("200000"),
        currency="IDR",
        is_taxable=False,
        description="Health premium",
    )


@pytest.fixture
def another_allowance():
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Meal Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("300000"),
        currency="IDR",
        is_taxable=True,
        description="Meals",
    )


@pytest.fixture
def another_deduction():
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Pension",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("100000"),
        currency="IDR",
        is_taxable=False,
        description="Pension fund",
    )


@pytest.fixture
def mock_employee_result(allowance_component, deduction_component):
    """Mock PayrollEmployeeResult object with required attributes."""
    class MockEmployee:
        def __init__(self):
            self.employee_id = uuid4()
            self.employee_name = "John Doe"
            self.gross_salary = Decimal("5000000")
            self.components = [allowance_component, deduction_component]
            self.tax = Decimal("300000")
            self.net_salary = Decimal("4500000")
            self.bank_account_number = "1234567890"
            self.payment_reference = "PAY-001"
            self.paid_at = datetime(2025, 2, 1, 10, 0, 0, tzinfo=UTC)
    return MockEmployee()


@pytest.fixture
def mock_payroll_run():
    """Mock PayrollRunEntity with required attributes."""
    class MockPayrollRun:
        def __init__(self):
            self.period_month = 1
            self.period_year = 2025
            self.run_number = "PR-2025-01"
            self.calculated_at = datetime(2025, 1, 31, 23, 59, 59, tzinfo=UTC)
            self.created_at = datetime(2025, 1, 30, 12, 0, 0, tzinfo=UTC)
    return MockPayrollRun()


@pytest.fixture
def valid_payslip(mock_employee_result, mock_payroll_run):
    """Create a valid PayslipProjection from the mock objects."""
    return PayslipProjection.from_payroll_employee(
        employee=mock_employee_result,
        payroll_run=mock_payroll_run,
        employee_nik="1234567890123456",
        employee_position="Senior Engineer",
    )


# ============================================================================
# Tests for PayslipProjection
# ============================================================================

class TestPayslipProjectionConstruction:
    def test_construction_valid(self, valid_payslip):
        assert valid_payslip.payslip_id is not None
        assert valid_payslip.employee_id is not None
        assert valid_payslip.employee_name == "John Doe"
        assert valid_payslip.period_month == 1
        assert valid_payslip.period_year == 2025
        assert valid_payslip.run_number == "PR-2025-01"
        assert valid_payslip.gross_salary == Decimal("5000000")
        assert valid_payslip.tax == Decimal("300000")
        assert valid_payslip.net_salary == Decimal("4500000")
        assert valid_payslip.employee_nik == "1234567890123456"
        assert valid_payslip.employee_position == "Senior Engineer"
        assert valid_payslip.bank_account_number == "1234567890"
        assert valid_payslip.payment_reference == "PAY-001"
        assert valid_payslip.payment_date == datetime(2025, 2, 1, 10, 0, 0, tzinfo=UTC)

    def test_validation_gross_salary_negative(self):
        with pytest.raises(ValueError, match="Gross salary cannot be negative"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=1,
                period_year=2025,
                run_number="PR-001",
                run_date=datetime.now(UTC),
                gross_salary=Decimal("-100"),
                allowances=[],
                deductions=[],
                tax=Decimal("0"),
                net_salary=Decimal("0"),
            )

    def test_validation_tax_negative(self):
        with pytest.raises(ValueError, match="Tax cannot be negative"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=1,
                period_year=2025,
                run_number="PR-001",
                run_date=datetime.now(UTC),
                gross_salary=Decimal("100"),
                allowances=[],
                deductions=[],
                tax=Decimal("-10"),
                net_salary=Decimal("90"),
            )

    def test_validation_net_salary_negative(self):
        with pytest.raises(ValueError, match="Net salary cannot be negative"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=1,
                period_year=2025,
                run_number="PR-001",
                run_date=datetime.now(UTC),
                gross_salary=Decimal("100"),
                allowances=[],
                deductions=[],
                tax=Decimal("0"),
                net_salary=Decimal("-10"),
            )

    def test_validation_run_date_naive(self):
        naive = datetime(2025, 1, 31, 23, 59, 59)
        with pytest.raises(ValueError, match="run_date must be timezone-aware"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=1,
                period_year=2025,
                run_number="PR-001",
                run_date=naive,
                gross_salary=Decimal("100"),
                allowances=[],
                deductions=[],
                tax=Decimal("0"),
                net_salary=Decimal("100"),
            )

    def test_validation_created_at_naive(self):
        naive = datetime(2025, 1, 31, 23, 59, 59)
        with pytest.raises(ValueError, match="created_at must be timezone-aware"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=1,
                period_year=2025,
                run_number="PR-001",
                run_date=datetime.now(UTC),
                gross_salary=Decimal("100"),
                allowances=[],
                deductions=[],
                tax=Decimal("0"),
                net_salary=Decimal("100"),
                created_at=naive,
            )

    def test_validation_period_month_invalid(self):
        with pytest.raises(ValueError, match="Invalid period month"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=13,
                period_year=2025,
                run_number="PR-001",
                run_date=datetime.now(UTC),
                gross_salary=Decimal("100"),
                allowances=[],
                deductions=[],
                tax=Decimal("0"),
                net_salary=Decimal("100"),
            )

    def test_validation_period_year_invalid(self):
        with pytest.raises(ValueError, match="Invalid period year"):
            PayslipProjection(
                payslip_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                period_month=1,
                period_year=1999,
                run_number="PR-001",
                run_date=datetime.now(UTC),
                gross_salary=Decimal("100"),
                allowances=[],
                deductions=[],
                tax=Decimal("0"),
                net_salary=Decimal("100"),
            )


class TestPayslipProjectionFactory:
    def test_from_payroll_employee(self, mock_employee_result, mock_payroll_run):
        payslip = PayslipProjection.from_payroll_employee(
            employee=mock_employee_result,
            payroll_run=mock_payroll_run,
            employee_nik="NIK-123",
            employee_position="Engineer",
        )
        assert payslip.employee_id == mock_employee_result.employee_id
        assert payslip.employee_name == mock_employee_result.employee_name
        assert payslip.gross_salary == mock_employee_result.gross_salary
        assert payslip.tax == mock_employee_result.tax
        assert payslip.net_salary == mock_employee_result.net_salary
        assert payslip.period_month == mock_payroll_run.period_month
        assert payslip.period_year == mock_payroll_run.period_year
        assert payslip.run_number == mock_payroll_run.run_number
        assert payslip.run_date == mock_payroll_run.calculated_at
        assert payslip.employee_nik == "NIK-123"
        assert payslip.employee_position == "Engineer"
        assert payslip.bank_account_number == mock_employee_result.bank_account_number
        assert payslip.payment_reference == mock_employee_result.payment_reference
        assert payslip.payment_date == mock_employee_result.paid_at
        # Check allowances and deductions are correctly split
        # allowances = components with positive amount, deductions = negative amount
        # In our fixture, allowance_component has +500000, deduction_component has -200000
        # Actually in the mock we passed allowance_component (positive) and deduction_component (negative)
        assert len(payslip.allowances) == 1
        assert payslip.allowances[0].amount == Decimal("500000")
        assert len(payslip.deductions) == 1
        assert payslip.deductions[0].amount == Decimal("-200000")  # negative

    def test_from_payroll_employee_without_nik_position(self, mock_employee_result, mock_payroll_run):
        payslip = PayslipProjection.from_payroll_employee(
            employee=mock_employee_result,
            payroll_run=mock_payroll_run,
        )
        assert payslip.employee_nik is None
        assert payslip.employee_position is None


class TestPayslipProjectionComputed:
    def test_get_total_allowances(self, valid_payslip):
        # valid_payslip has one allowance of 500000
        assert valid_payslip.get_total_allowances() == Decimal("500000")

        # Add another allowance via a new payslip (but we can't modify frozen)
        # We'll create a new payslip with additional allowance
        new_allowance = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="Bonus",
            component_type=ComponentType.ALLOWANCE,
            amount=Decimal("200000"),
            currency="IDR",
            is_taxable=True,
        )
        # We'll create a payslip with both allowances
        allowances = [*valid_payslip.allowances, new_allowance]
        payslip2 = PayslipProjection(
            payslip_id=uuid4(),
            employee_id=valid_payslip.employee_id,
            employee_name=valid_payslip.employee_name,
            period_month=valid_payslip.period_month,
            period_year=valid_payslip.period_year,
            run_number=valid_payslip.run_number,
            run_date=valid_payslip.run_date,
            gross_salary=valid_payslip.gross_salary,
            allowances=allowances,
            deductions=valid_payslip.deductions,
            tax=valid_payslip.tax,
            net_salary=valid_payslip.net_salary,
        )
        assert payslip2.get_total_allowances() == Decimal("700000")

    def test_get_total_deductions(self, valid_payslip):
        # valid_payslip has one deduction of -200000, absolute value 200000
        assert valid_payslip.get_total_deductions() == Decimal("200000")

        # Add another deduction
        new_deduction = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="Loan",
            component_type=ComponentType.DEDUCTION,
            amount=Decimal("150000"),
            currency="IDR",
            is_taxable=False,
        )
        deductions = [*valid_payslip.deductions, new_deduction]
        payslip2 = PayslipProjection(
            payslip_id=uuid4(),
            employee_id=valid_payslip.employee_id,
            employee_name=valid_payslip.employee_name,
            period_month=valid_payslip.period_month,
            period_year=valid_payslip.period_year,
            run_number=valid_payslip.run_number,
            run_date=valid_payslip.run_date,
            gross_salary=valid_payslip.gross_salary,
            allowances=valid_payslip.allowances,
            deductions=deductions,
            tax=valid_payslip.tax,
            net_salary=valid_payslip.net_salary,
        )
        assert payslip2.get_total_deductions() == Decimal("350000")

    def test_get_component_summary(self, valid_payslip):
        summary = valid_payslip.get_component_summary()
        assert summary["ALLOWANCE_Transport Allowance"] == Decimal("500000")
        assert summary["DEDUCTION_Health Insurance"] == Decimal("200000")
        assert summary["TAX"] == Decimal("300000")
        # Ensure no other keys
        assert len(summary) == 3


class TestPayslipProjectionSerialization:
    def test_to_dict(self, valid_payslip):
        d = valid_payslip.to_dict()
        assert d["payslip_id"] == str(valid_payslip.payslip_id)
        assert d["employee_id"] == str(valid_payslip.employee_id)
        assert d["employee_name"] == "John Doe"
        assert d["employee_nik"] == "1234567890123456"
        assert d["employee_position"] == "Senior Engineer"
        assert d["period"] == "1/2025"
        assert d["run_number"] == "PR-2025-01"
        assert d["gross_salary"] == "5000000"
        assert d["total_allowances"] == "500000"
        assert d["total_deductions"] == "200000"
        assert d["tax"] == "300000"
        assert d["net_salary"] == "4500000"
        assert d["bank_account_number"] == "1234567890"
        assert d["payment_reference"] == "PAY-001"
        assert "components" in d
        assert len(d["components"]["allowances"]) == 1
        assert len(d["components"]["deductions"]) == 1
        assert d["created_at"] is not None


class TestPayslipProjectionHtmlPdf:
    def test_generate_html(self, valid_payslip):
        html = valid_payslip.generate_html()
        assert "<html>" in html
        assert "PT Company Name" in html
        assert "SLIP GAJI" in html
        assert "John Doe" in html
        assert "Senior Engineer" in html
        assert "5000000" in html
        assert "Transport Allowance" in html
        assert "Health Insurance" in html
        assert "200000" in html
        assert "4500000" in html
        assert "Take Home Pay" in html
        assert "Dicetak oleh sistem" in html

    def test_generate_pdf(self, valid_payslip):
        pdf_bytes = valid_payslip.generate_pdf()
        assert isinstance(pdf_bytes, bytes)
        # PDF is actually HTML bytes in this implementation
        assert b"<html>" in pdf_bytes


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestPayslipRepository:
    def test_abstract_methods_raise(self):
        repo = PayslipRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_employee(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_period(uuid4(), 2025, 1)
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
