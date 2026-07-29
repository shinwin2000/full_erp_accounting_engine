# tests/infrastructure/persistence_orm/test_employee_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/employee_table.py
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.employee_table import EmployeeTable


class TestEmployeeTable:
    """Tests for the EmployeeTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(EmployeeTable, "__tablename__")
        assert isinstance(EmployeeTable.__tablename__, str)
        assert len(EmployeeTable.__tablename__) > 0

    def test_instantiation(self):
        instance = EmployeeTable(
            id=uuid4(),
            employee_code="EMP001",
            full_name="John Doe",
            employment_status="active",
            is_active=True,
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            ptkp_status="TK/0",
        )
        assert isinstance(instance, EmployeeTable)
        assert instance.employee_code == "EMP001"
        assert instance.full_name == "John Doe"

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def employee(self):
        return EmployeeTable(
            id=uuid4(),
            employee_code="EMP001",
            full_name="John Doe",
            birth_date=date(1990, 5, 15),
            marital_status="single",
            employment_status="active",
            is_active=True,
            basic_salary=Decimal("5000000"),
            allowances=Decimal("1000000"),
            bpjs_jht_rate_employee=Decimal("2.0"),
            bpjs_kesehatan_rate_employee=Decimal("1.0"),
            bpjs_jht_rate_employer=Decimal("3.7"),
            bpjs_jkk_rate=Decimal("0.24"),
            bpjs_jkm_rate=Decimal("0.30"),
            bpjs_kesehatan_rate_employer=Decimal("4.0"),
            annual_leave_balance=Decimal("12"),
            sick_leave_balance=Decimal("14"),
            special_leave_balance=Decimal("0"),
            version=1,
        )

    @pytest.fixture
    def inactive_employee(self):
        return EmployeeTable(
            id=uuid4(),
            employee_code="EMP002",
            full_name="Jane Doe",
            employment_status="inactive",
            is_active=False,
            basic_salary=Decimal("6000000"),
            version=1,
        )

    @pytest.fixture
    def resigned_employee(self):
        return EmployeeTable(
            id=uuid4(),
            employee_code="EMP003",
            full_name="Bob Smith",
            employment_status="resigned",
            is_active=False,
            resignation_date=date(2026, 6, 30),
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_age(self, employee):
        # Mock date.today to a fixed date
        with patch("infrastructure.persistence_orm.employee_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            assert employee.age == 36  # 2026 - 1990 = 36, birthday May 15 already passed

            # Test birthday not passed yet
            employee.birth_date = date(1990, 8, 15)
            assert employee.age == 35  # 2026 - 1990 - 1 = 35

            # No birth_date
            employee.birth_date = None
            assert employee.age is None

    def test_is_active_employee(self, employee, inactive_employee):
        assert employee.is_active_employee is True
        assert inactive_employee.is_active_employee is False

        # active but is_active False
        employee.is_active = False
        assert employee.is_active_employee is False

    def test_is_resigned(self, employee, resigned_employee):
        assert employee.is_resigned is False
        assert resigned_employee.is_resigned is True

    def test_total_annual_salary(self, employee):
        # basic 5,000,000 + allowances 1,000,000 = 6,000,000 * 12 = 72,000,000
        assert employee.total_annual_salary == Decimal("72000000")

    def test_monthly_taxable_income(self, employee):
        # basic 5,000,000 + allowances 1,000,000 = 6,000,000
        # bpjs deduction = 5,000,000 * (2.0/100 + 1.0/100) = 5,000,000 * 0.03 = 150,000
        # taxable = 6,000,000 - 150,000 = 5,850,000
        expected = Decimal("5850000")
        assert employee.monthly_taxable_income == expected

    def test_bpjs_employee_total_rate(self, employee):
        # 2.0 + 1.0 = 3.0
        assert employee.bpjs_employee_total_rate == Decimal("3.0")

    def test_bpjs_employer_total_rate(self, employee):
        # 3.7 + 0.24 + 0.30 + 4.0 = 8.24
        assert employee.bpjs_employer_total_rate == Decimal("8.24")

    # -------------------- Method Tests --------------------
    def test_activate(self, inactive_employee):
        inactive_employee.activate()
        assert inactive_employee.employment_status == "active"
        assert inactive_employee.is_active is True
        assert inactive_employee.version == 2

    def test_deactivate(self, employee):
        employee.deactivate()
        assert employee.employment_status == "inactive"
        assert employee.is_active is False
        assert employee.version == 2

    def test_resign(self, employee):
        resign_date = date(2026, 7, 31)
        employee.resign(resign_date)
        assert employee.employment_status == "resigned"
        assert employee.resignation_date == resign_date
        assert employee.is_active is False
        assert employee.version == 2

    def test_terminate(self, employee):
        term_date = date(2026, 7, 31)
        employee.terminate(term_date, reason="Performance issues")
        assert employee.employment_status == "terminated"
        assert employee.resignation_date == term_date
        assert employee.is_active is False
        assert employee.version == 2
        assert employee.extra_metadata["termination_reason"] == "Performance issues"

    def test_terminate_without_reason(self, employee):
        term_date = date(2026, 7, 31)
        employee.terminate(term_date)
        assert employee.employment_status == "terminated"
        assert employee.extra_metadata is None  # no reason, no metadata created

    def test_update_salary(self, employee):
        old_salary = employee.basic_salary
        new_salary = Decimal("6000000")
        effective_date = date(2026, 7, 1)
        employee.update_salary(new_salary, effective_date)
        assert employee.basic_salary == new_salary
        assert employee.version == 2
        assert employee.extra_metadata is not None
        assert "salary_history" in employee.extra_metadata
        history = employee.extra_metadata["salary_history"]
        assert len(history) == 1
        assert history[0]["date"] == effective_date.isoformat()
        assert history[0]["old_salary"] == float(old_salary)
        assert history[0]["new_salary"] == float(new_salary)

    def test_update_salary_multiple_times(self, employee):
        employee.update_salary(Decimal("6000000"), date(2026, 7, 1))
        employee.update_salary(Decimal("7000000"), date(2026, 8, 1))
        history = employee.extra_metadata["salary_history"]
        assert len(history) == 2
        assert history[0]["old_salary"] == 5000000.0
        assert history[0]["new_salary"] == 6000000.0
        assert history[1]["old_salary"] == 6000000.0
        assert history[1]["new_salary"] == 7000000.0

    def test_has_available_leave_annual(self, employee):
        assert employee.has_available_leave("annual", Decimal("5")) is True
        assert employee.has_available_leave("annual", Decimal("12")) is True
        assert employee.has_available_leave("annual", Decimal("13")) is False

    def test_has_available_leave_sick(self, employee):
        assert employee.has_available_leave("sick", Decimal("10")) is True
        assert employee.has_available_leave("sick", Decimal("14")) is True
        assert employee.has_available_leave("sick", Decimal("15")) is False

    def test_has_available_leave_special(self, employee):
        assert employee.has_available_leave("special", Decimal("0")) is True
        assert employee.has_available_leave("special", Decimal("1")) is False

    def test_has_available_leave_invalid_type(self, employee):
        assert employee.has_available_leave("invalid", Decimal("1")) is False

    def test_deduct_leave_annual(self, employee):
        employee.deduct_leave("annual", Decimal("2"))
        assert employee.annual_leave_balance == Decimal("10")
        assert employee.version == 2

    def test_deduct_leave_sick(self, employee):
        employee.deduct_leave("sick", Decimal("3"))
        assert employee.sick_leave_balance == Decimal("11")
        assert employee.version == 2

    def test_deduct_leave_special(self, employee):
        employee.special_leave_balance = Decimal("5")
        employee.deduct_leave("special", Decimal("2"))
        assert employee.special_leave_balance == Decimal("3")
        assert employee.version == 2

    def test_deduct_leave_invalid_type(self, employee):
        # Should not raise but also not deduct anything
        initial_version = employee.version
        employee.deduct_leave("invalid", Decimal("1"))
        assert employee.annual_leave_balance == Decimal("12")
        assert employee.sick_leave_balance == Decimal("14")
        assert employee.special_leave_balance == Decimal("0")
        assert employee.version == initial_version  # no change

    def test_reset_leave_balance(self, employee):
        employee.annual_leave_balance = Decimal("5")
        employee.sick_leave_balance = Decimal("3")
        employee.special_leave_balance = Decimal("2")
        employee.reset_leave_balance(annual_days=20, sick_days=15)
        assert employee.annual_leave_balance == Decimal("20")
        assert employee.sick_leave_balance == Decimal("15")
        assert employee.special_leave_balance == Decimal("0")
        assert employee.version == 2

    def test_reset_leave_balance_default(self, employee):
        employee.annual_leave_balance = Decimal("5")
        employee.sick_leave_balance = Decimal("3")
        employee.reset_leave_balance()
        assert employee.annual_leave_balance == Decimal("12")
        assert employee.sick_leave_balance == Decimal("14")
        assert employee.special_leave_balance == Decimal("0")
        assert employee.version == 2

    # -------------------- to_dict Tests --------------------
    def test_to_dict(self, employee):
        d = employee.to_dict()
        assert d["employee_code"] == "EMP001"
        assert d["full_name"] == "John Doe"
        assert d["basic_salary"] == float(employee.basic_salary)
        assert d["allowances"] == float(employee.allowances)
        assert d["total_annual_salary"] == float(employee.total_annual_salary)
        assert d["monthly_taxable_income"] == float(employee.monthly_taxable_income)
        assert d["annual_leave_balance"] == float(employee.annual_leave_balance)
        assert d["sick_leave_balance"] == float(employee.sick_leave_balance)
        assert d["is_active"] is True
        assert d["version"] == 1

    # -------------------- Negative / Edge Cases --------------------
    def test_age_with_leap_year_birthday(self):
        emp = EmployeeTable(birth_date=date(2020, 2, 29))
        with patch("infrastructure.persistence_orm.employee_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 2, 28)
            # Should still work
            assert emp.age == 5  # 2026 - 2020 = 6? Wait 2026 - 2020 = 6, but birthday is Feb 29, so if today is Feb 28, birthday not passed, age = 5
            # Actually calculation: 2026 - 2020 - ((month, day) < (2, 29)) -> (2,28) < (2,29) is True, so 6 - 1 = 5
            assert emp.age == 5

            mock_date.today.return_value = date(2026, 3, 1)
            # (3,1) < (2,29) is False, so age = 6
            assert emp.age == 6

    def test_monthly_taxable_income_zero_basic(self):
        emp = EmployeeTable(
            basic_salary=Decimal("0"),
            allowances=Decimal("0"),
            bpjs_jht_rate_employee=Decimal("2.0"),
            bpjs_kesehatan_rate_employee=Decimal("1.0"),
        )
        assert emp.monthly_taxable_income == Decimal("0")

    def test_monthly_taxable_income_no_allowances(self):
        emp = EmployeeTable(
            basic_salary=Decimal("5000000"),
            allowances=Decimal("0"),
            bpjs_jht_rate_employee=Decimal("2.0"),
            bpjs_kesehatan_rate_employee=Decimal("1.0"),
        )
        # bpjs deduction = 5,000,000 * 0.03 = 150,000
        # taxable = 5,000,000 - 150,000 = 4,850,000
        assert emp.monthly_taxable_income == Decimal("4850000")

    def test_update_salary_creates_extra_metadata(self):
        emp = EmployeeTable(
            employee_code="EMP999",
            full_name="Test",
            basic_salary=Decimal("1000000"),
            allowances=Decimal("0"),
        )
        assert emp.extra_metadata is None
        emp.update_salary(Decimal("2000000"), date.today())
        assert emp.extra_metadata is not None
        assert "salary_history" in emp.extra_metadata

    def test_terminate_with_reason_creates_extra_metadata(self):
        emp = EmployeeTable(
            employee_code="EMP999",
            full_name="Test",
            basic_salary=Decimal("1000000"),
        )
        assert emp.extra_metadata is None
        emp.terminate(date.today(), reason="Fired")
        assert emp.extra_metadata is not None
        assert emp.extra_metadata["termination_reason"] == "Fired"

    def test_terminate_without_reason_no_metadata(self):
        emp = EmployeeTable(
            employee_code="EMP999",
            full_name="Test",
            basic_salary=Decimal("1000000"),
        )
        emp.terminate(date.today())
        assert emp.extra_metadata is None
