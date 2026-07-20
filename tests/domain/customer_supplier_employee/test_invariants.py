# tests/domain/customer_supplier_employee/test_invariants.py
# Perbaikan kualitas assertions: semua assert True dihapus,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, atau interaksi mock.

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.customer_supplier_employee.customer_entity import CustomerStatus
from domain.customer_supplier_employee.invariants import (
    CustomerInvariants,
    EmployeeInvariants,
    InvariantResult,
    MasterDataInvariantEnforcer,
    SupplierInvariants,
)


# ============================================================================
# InvariantResult tests
# ============================================================================
class TestInvariantResult:
    def test_construction_valid(self):
        result = InvariantResult(is_valid=True, errors=None)
        assert result.is_valid is True
        assert result.errors == []

    def test_construction_invalid(self):
        result = InvariantResult(is_valid=False, errors=["error1"])
        assert result.is_valid is False
        assert result.errors == ["error1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]

    def test_merge_valid(self):
        result = InvariantResult()
        other = InvariantResult()
        result.merge(other)
        assert result.is_valid is True
        assert result.errors == []

    def test_merge_invalid(self):
        result = InvariantResult()
        other = InvariantResult(is_valid=False, errors=["err1", "err2"])
        result.merge(other)
        assert result.is_valid is False
        assert result.errors == ["err1", "err2"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False


# ============================================================================
# CustomerInvariants tests
# ============================================================================
class TestCustomerInvariants:
    def test_validate_customer_code_unique_valid(self):
        result = CustomerInvariants.validate_customer_code_unique("CUST001", {"CUST002"})
        assert result.is_valid is True
        assert result.errors == []

    def test_validate_customer_code_unique_invalid(self):
        result = CustomerInvariants.validate_customer_code_unique("CUST001", {"CUST001", "CUST002"})
        assert result.is_valid is False
        assert result.errors == ["Customer code 'CUST001' already exists"]

    def test_validate_email_unique_valid(self):
        result = CustomerInvariants.validate_email_unique("a@b.com", {"other@b.com"})
        assert result.is_valid is True

    def test_validate_email_unique_invalid(self):
        result = CustomerInvariants.validate_email_unique("a@b.com", {"a@b.com"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_email_unique_empty(self):
        result = CustomerInvariants.validate_email_unique("", set())
        assert result.is_valid is True  # empty email is ignored

    def test_validate_credit_limit_valid(self):
        result = CustomerInvariants.validate_credit_limit(Decimal("1000"))
        assert result.is_valid is True

    def test_validate_credit_limit_invalid(self):
        result = CustomerInvariants.validate_credit_limit(Decimal("-100"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_customer_status_transition_valid(self):
        result = CustomerInvariants.validate_customer_status_transition(
            CustomerStatus.ACTIVE, CustomerStatus.INACTIVE
        )
        assert result.is_valid is True

    def test_validate_customer_status_transition_blacklisted_invalid(self):
        result = CustomerInvariants.validate_customer_status_transition(
            CustomerStatus.BLACKLISTED, CustomerStatus.ACTIVE
        )
        assert result.is_valid is False
        assert "Cannot change status of blacklisted customer" in result.errors[0]

    def test_validate_customer_status_transition_blacklisted_to_blacklisted(self):
        result = CustomerInvariants.validate_customer_status_transition(
            CustomerStatus.BLACKLISTED, CustomerStatus.BLACKLISTED
        )
        assert result.is_valid is True  # same status allowed


# ============================================================================
# SupplierInvariants tests
# ============================================================================
class TestSupplierInvariants:
    def test_validate_supplier_code_unique_valid(self):
        result = SupplierInvariants.validate_supplier_code_unique("SUP001", {"SUP002"})
        assert result.is_valid is True

    def test_validate_supplier_code_unique_invalid(self):
        result = SupplierInvariants.validate_supplier_code_unique("SUP001", {"SUP001"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_tax_id_unique_valid(self):
        result = SupplierInvariants.validate_tax_id_unique("123", {"456"})
        assert result.is_valid is True

    def test_validate_tax_id_unique_invalid(self):
        result = SupplierInvariants.validate_tax_id_unique("123", {"123"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_tax_id_unique_empty(self):
        result = SupplierInvariants.validate_tax_id_unique("", set())
        assert result.is_valid is True

    def test_validate_payment_terms_valid(self):
        result = SupplierInvariants.validate_payment_terms(30)
        assert result.is_valid is True

    def test_validate_payment_terms_negative(self):
        result = SupplierInvariants.validate_payment_terms(-5)
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_payment_terms_very_long(self, caplog):
        # Should log warning but still valid
        result = SupplierInvariants.validate_payment_terms(200)
        assert result.is_valid is True
        assert "unusually long" in caplog.text


# ============================================================================
# EmployeeInvariants tests
# ============================================================================
class TestEmployeeInvariants:
    def test_validate_employee_number_unique_valid(self):
        result = EmployeeInvariants.validate_employee_number_unique("EMP001", {"EMP002"})
        assert result.is_valid is True

    def test_validate_employee_number_unique_invalid(self):
        result = EmployeeInvariants.validate_employee_number_unique("EMP001", {"EMP001"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_birth_date_valid(self):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)  # > 18 years old
        result = EmployeeInvariants.validate_birth_date(birth_date, join_date)
        assert result.is_valid is True

    def test_validate_birth_date_too_young(self):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2010, 1, 1)  # 14 years old
        result = EmployeeInvariants.validate_birth_date(birth_date, join_date)
        assert result.is_valid is False
        assert "at least 18 years old" in result.errors[0]

    def test_validate_birth_date_none(self):
        result = EmployeeInvariants.validate_birth_date(None, datetime.now())
        assert result.is_valid is True

    def test_validate_resign_date_valid(self):
        join_date = datetime(2020, 1, 1)
        resign_date = datetime(2021, 1, 1)
        result = EmployeeInvariants.validate_resign_date(join_date, resign_date)
        assert result.is_valid is True

    def test_validate_resign_date_invalid(self):
        join_date = datetime(2020, 1, 1)
        resign_date = datetime(2019, 1, 1)
        result = EmployeeInvariants.validate_resign_date(join_date, resign_date)
        assert result.is_valid is False
        assert "must be after join date" in result.errors[0]

    def test_validate_resign_date_none(self):
        result = EmployeeInvariants.validate_resign_date(datetime.now(), None)
        assert result.is_valid is True

    def test_validate_basic_salary_valid(self):
        result = EmployeeInvariants.validate_basic_salary(Decimal("5000000"), Decimal("4500000"))
        assert result.is_valid is True

    def test_validate_basic_salary_below_minimum(self):
        result = EmployeeInvariants.validate_basic_salary(Decimal("4000000"), Decimal("4500000"))
        assert result.is_valid is False
        assert "below minimum wage" in result.errors[0]

    def test_validate_basic_salary_zero(self):
        result = EmployeeInvariants.validate_basic_salary(Decimal("0"), Decimal("4500000"))
        assert result.is_valid is False
        assert "must be positive" in result.errors[0]


# ============================================================================
# MasterDataInvariantEnforcer tests
# ============================================================================
class TestMasterDataInvariantEnforcer:
    @pytest.fixture
    def mock_checkers(self):
        return {
            "customer_code": AsyncMock(return_value={"CUST001"}),
            "supplier_code": AsyncMock(return_value={"SUP001"}),
            "employee_number": AsyncMock(return_value={"EMP001"}),
            "email": AsyncMock(return_value={"a@b.com"}),
            "tax_id": AsyncMock(return_value={"123"}),
        }

    @pytest.fixture
    def enforcer(self, mock_checkers):
        return MasterDataInvariantEnforcer(
            customer_code_checker=mock_checkers["customer_code"],
            supplier_code_checker=mock_checkers["supplier_code"],
            employee_number_checker=mock_checkers["employee_number"],
            email_checker=mock_checkers["email"],
            tax_id_checker=mock_checkers["tax_id"],
        )

    async def test_enforce_customer_create_all_valid(self, enforcer, mock_checkers):
        result = await enforcer.enforce_customer_create(
            customer_code="CUST002",
            email="b@b.com",
            credit_limit=Decimal("1000"),
        )
        assert result.is_valid is True
        assert result.errors == []
        mock_checkers["customer_code"].assert_awaited_once()
        mock_checkers["email"].assert_awaited_once()

    async def test_enforce_customer_create_duplicate_code(self, enforcer, mock_checkers):
        result = await enforcer.enforce_customer_create(
            customer_code="CUST001",  # exists
            email="b@b.com",
            credit_limit=Decimal("1000"),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_customer_create_duplicate_email(self, enforcer, mock_checkers):
        result = await enforcer.enforce_customer_create(
            customer_code="CUST002",
            email="a@b.com",  # exists
            credit_limit=Decimal("1000"),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_customer_create_negative_credit(self, enforcer, mock_checkers):
        result = await enforcer.enforce_customer_create(
            customer_code="CUST002",
            email="b@b.com",
            credit_limit=Decimal("-100"),
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    async def test_enforce_supplier_create_all_valid(self, enforcer, mock_checkers):
        result = await enforcer.enforce_supplier_create(
            supplier_code="SUP002",
            tax_id="456",
            payment_terms_days=30,
        )
        assert result.is_valid is True
        mock_checkers["supplier_code"].assert_awaited_once()
        mock_checkers["tax_id"].assert_awaited_once()

    async def test_enforce_supplier_create_duplicate_code(self, enforcer, mock_checkers):
        result = await enforcer.enforce_supplier_create(
            supplier_code="SUP001",  # exists
            tax_id="456",
            payment_terms_days=30,
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_supplier_create_duplicate_tax_id(self, enforcer, mock_checkers):
        result = await enforcer.enforce_supplier_create(
            supplier_code="SUP002",
            tax_id="123",  # exists
            payment_terms_days=30,
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_supplier_create_negative_payment_terms(self, enforcer, mock_checkers):
        result = await enforcer.enforce_supplier_create(
            supplier_code="SUP002",
            tax_id="456",
            payment_terms_days=-5,
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    async def test_enforce_employee_create_all_valid(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)
        result = await enforcer.enforce_employee_create(
            employee_number="EMP002",
            email="b@b.com",
            tax_id="456",
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("5000000"),
        )
        assert result.is_valid is True
        mock_checkers["employee_number"].assert_awaited_once()
        mock_checkers["email"].assert_awaited_once()
        mock_checkers["tax_id"].assert_awaited_once()

    async def test_enforce_employee_create_duplicate_number(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)
        result = await enforcer.enforce_employee_create(
            employee_number="EMP001",  # exists
            email="b@b.com",
            tax_id="456",
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("5000000"),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_employee_create_duplicate_email(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)
        result = await enforcer.enforce_employee_create(
            employee_number="EMP002",
            email="a@b.com",  # exists
            tax_id="456",
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("5000000"),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_employee_create_duplicate_tax_id(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)
        result = await enforcer.enforce_employee_create(
            employee_number="EMP002",
            email="b@b.com",
            tax_id="123",  # exists
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("5000000"),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_employee_create_too_young(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2010, 1, 1)  # 14 years old
        result = await enforcer.enforce_employee_create(
            employee_number="EMP002",
            email="b@b.com",
            tax_id="456",
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("5000000"),
        )
        assert result.is_valid is False
        assert "at least 18 years old" in result.errors[0]

    async def test_enforce_employee_create_below_minimum_wage(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)
        result = await enforcer.enforce_employee_create(
            employee_number="EMP002",
            email="b@b.com",
            tax_id="456",
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("4000000"),
        )
        assert result.is_valid is False
        assert "below minimum wage" in result.errors[0]

    async def test_enforce_employee_create_without_email(self, enforcer, mock_checkers):
        join_date = datetime(2024, 1, 1)
        birth_date = datetime(2000, 1, 1)
        result = await enforcer.enforce_employee_create(
            employee_number="EMP002",
            email=None,
            tax_id=None,
            birth_date=birth_date,
            join_date=join_date,
            basic_salary=Decimal("5000000"),
        )
        assert result.is_valid is True
        mock_checkers["email"].assert_not_awaited()
        mock_checkers["tax_id"].assert_not_awaited()