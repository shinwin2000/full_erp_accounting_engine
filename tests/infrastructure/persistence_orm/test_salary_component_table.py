# tests/infrastructure/persistence_orm/test_salary_component_table.py
# Comprehensive tests for infrastructure/persistence_orm/salary_component_table.py

from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.salary_component_table import SalaryComponentTable


class TestSalaryComponentTable:
    """Tests for the SalaryComponentTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(SalaryComponentTable, "__tablename__")
        assert isinstance(SalaryComponentTable.__tablename__, str)
        assert len(SalaryComponentTable.__tablename__) > 0

    def test_instantiation(self):
        instance = SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="Basic Salary",
            component_type="earnings",
            calculation_type="fixed",
            amount=Decimal("5000000"),
            currency="IDR",
            description="Monthly basic salary",
        )
        assert isinstance(instance, SalaryComponentTable)
        assert instance.component_name == "Basic Salary"
        assert instance.amount == Decimal("5000000")

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def fixed_earnings(self):
        return SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="Basic Salary",
            component_type="earnings",
            calculation_type="fixed",
            amount=Decimal("5000000"),
            rate_percentage=None,
            currency="IDR",
            description="Monthly basic salary",
            version=1,
        )

    @pytest.fixture
    def fixed_deduction(self):
        return SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="BPJS Employment",
            component_type="deductions",
            calculation_type="fixed",
            amount=Decimal("100000"),
            rate_percentage=None,
            currency="IDR",
            description="BPJS Ketenagakerjaan",
            version=1,
        )

    @pytest.fixture
    def fixed_tax(self):
        return SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="PPH 21",
            component_type="tax",
            calculation_type="fixed",
            amount=Decimal("500000"),
            rate_percentage=None,
            currency="IDR",
            description="Income tax",
            version=1,
        )

    @pytest.fixture
    def percentage_earnings(self):
        return SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="Performance Bonus",
            component_type="earnings",
            calculation_type="percentage",
            amount=Decimal("5000000"),  # base amount
            rate_percentage=Decimal("10"),  # 10% of base
            currency="IDR",
            description="Performance bonus 10%",
            version=1,
        )

    @pytest.fixture
    def percentage_deduction(self):
        return SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="Pension",
            component_type="deductions",
            calculation_type="percentage",
            amount=Decimal("5000000"),  # base amount
            rate_percentage=Decimal("5"),  # 5% of base
            currency="IDR",
            description="Pension contribution 5%",
            version=1,
        )

    @pytest.fixture
    def percentage_without_rate(self):
        return SalaryComponentTable(
            id=uuid4(),
            employee_id=uuid4(),
            payroll_run_id=uuid4(),
            component_name="Bonus",
            component_type="earnings",
            calculation_type="percentage",
            amount=Decimal("1000000"),
            rate_percentage=None,
            currency="IDR",
            description="Bonus without rate",
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_is_earnings_true(self, fixed_earnings):
        assert fixed_earnings.is_earnings is True
        # Check other types return False
        assert fixed_earnings.is_deduction is False
        assert fixed_earnings.is_tax is False

    def test_is_deduction_true(self, fixed_deduction):
        assert fixed_deduction.is_deduction is True
        assert fixed_deduction.is_earnings is False
        assert fixed_deduction.is_tax is False

    def test_is_tax_true(self, fixed_tax):
        assert fixed_tax.is_tax is True
        assert fixed_tax.is_earnings is False
        assert fixed_tax.is_deduction is False

    def test_is_fixed_true(self, fixed_earnings):
        assert fixed_earnings.is_fixed is True
        assert fixed_earnings.is_percentage is False

    def test_is_percentage_true(self, percentage_earnings):
        assert percentage_earnings.is_percentage is True
        assert percentage_earnings.is_fixed is False

    def test_is_percentage_earnings_combination(self, percentage_earnings):
        assert percentage_earnings.is_earnings is True
        assert percentage_earnings.is_percentage is True

    # -------------------- computed_amount Tests --------------------
    def test_computed_amount_fixed(self, fixed_earnings):
        # Fixed amount should return the amount directly
        assert fixed_earnings.computed_amount == Decimal("5000000")

    def test_computed_amount_percentage_with_rate(self, percentage_earnings):
        # amount = 5,000,000, rate = 10% => 5,000,000 * 0.10 = 500,000
        expected = Decimal("500000")
        assert percentage_earnings.computed_amount == expected

    def test_computed_amount_percentage_deduction(self, percentage_deduction):
        # amount = 5,000,000, rate = 5% => 5,000,000 * 0.05 = 250,000
        expected = Decimal("250000")
        assert percentage_deduction.computed_amount == expected

    def test_computed_amount_percentage_with_zero_rate(self):
        component = SalaryComponentTable(
            component_type="earnings",
            calculation_type="percentage",
            amount=Decimal("1000000"),
            rate_percentage=Decimal(0),
        )
        assert component.computed_amount == Decimal(0)

    def test_computed_amount_percentage_without_rate(self, percentage_without_rate):
        # When rate_percentage is None, should return amount (fallback)
        assert percentage_without_rate.computed_amount == Decimal("1000000")

    def test_computed_amount_percentage_with_high_precision(self):
        component = SalaryComponentTable(
            component_type="earnings",
            calculation_type="percentage",
            amount=Decimal("1234567"),
            rate_percentage=Decimal("7.5"),
        )
        # 1,234,567 * 7.5 / 100 = 92,592.525 -> quantize to 0.01 => 92,592.53
        expected = (Decimal("1234567") * Decimal("7.5") / Decimal("100")).quantize(Decimal("0.01"))
        assert component.computed_amount == expected

    # -------------------- to_dict Tests --------------------
    def test_to_dict_fixed_earnings(self, fixed_earnings):
        d = fixed_earnings.to_dict()
        assert d["component_name"] == "Basic Salary"
        assert d["component_type"] == "earnings"
        assert d["calculation_type"] == "fixed"
        # Amount should be string to preserve precision
        assert d["amount"] == "5000000"
        assert d["rate_percentage"] is None
        assert d["computed_amount"] == "5000000"
        assert d["currency"] == "IDR"
        assert d["description"] == "Monthly basic salary"
        assert "id" in d
        assert "employee_id" in d
        assert "payroll_run_id" in d

    def test_to_dict_percentage_earnings(self, percentage_earnings):
        d = percentage_earnings.to_dict()
        assert d["component_name"] == "Performance Bonus"
        assert d["component_type"] == "earnings"
        assert d["calculation_type"] == "percentage"
        assert d["amount"] == "5000000"
        assert d["rate_percentage"] == 10.0  # float for rate_percentage
        assert d["computed_amount"] == "500000"  # 5,000,000 * 10%

    def test_to_dict_percentage_deduction(self, percentage_deduction):
        d = percentage_deduction.to_dict()
        assert d["component_name"] == "Pension"
        assert d["component_type"] == "deductions"
        assert d["rate_percentage"] == 5.0
        assert d["computed_amount"] == "250000"

    def test_to_dict_without_rate(self, percentage_without_rate):
        d = percentage_without_rate.to_dict()
        assert d["rate_percentage"] is None
        assert d["computed_amount"] == "1000000"

    # -------------------- Edge Cases and Validation --------------------
    def test_computed_amount_with_decimal_rate(self):
        component = SalaryComponentTable(
            component_type="earnings",
            calculation_type="percentage",
            amount=Decimal("1000000"),
            rate_percentage=Decimal("12.5"),
        )
        # 1,000,000 * 12.5 / 100 = 125,000
        assert component.computed_amount == Decimal("125000")

    def test_computed_amount_very_large_values(self):
        component = SalaryComponentTable(
            component_type="earnings",
            calculation_type="percentage",
            amount=Decimal("9999999999999999"),
            rate_percentage=Decimal("99.99"),
        )
        expected = (Decimal("9999999999999999") * Decimal("99.99") / Decimal("100")).quantize(Decimal("0.01"))
        assert component.computed_amount == expected

    def test_all_properties_combination(self):
        # Test a component that is both earnings and percentage
        component = SalaryComponentTable(
            component_type="earnings",
            calculation_type="percentage",
        )
        assert component.is_earnings is True
        assert component.is_deduction is False
        assert component.is_tax is False
        assert component.is_fixed is False
        assert component.is_percentage is True

        # Test a component that is fixed and deduction
        component2 = SalaryComponentTable(
            component_type="deductions",
            calculation_type="fixed",
        )
        assert component2.is_deduction is True
        assert component2.is_fixed is True
        assert component2.is_percentage is False

    def test_to_dict_contains_all_required_fields(self, fixed_earnings):
        d = fixed_earnings.to_dict()
        required_fields = [
            "id",
            "employee_id",
            "payroll_run_id",
            "component_name",
            "component_type",
            "calculation_type",
            "amount",
            "rate_percentage",
            "computed_amount",
            "currency",
            "description",
            "legal_entity_id",
        ]
        for field in required_fields:
            assert field in d
