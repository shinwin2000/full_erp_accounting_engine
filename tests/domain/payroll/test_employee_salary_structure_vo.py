# test_employee_salary_structure_vo.py
# Comprehensive tests for employee_salary_structure_vo.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
    BPJSEmploymentProgram,
    BPJSType,
    EmployeeBPJSEnrollmentVO,
)
from domain.customer_supplier_employee.employee_ptkp_status_vo import (
    EmployeePTKPStatusVO,
    MaritalStatus,
)
from domain.payroll.employee_salary_structure_vo import (
    EmployeeSalaryStructureVO,
    SalaryComponentEntity,
)
from domain.payroll.salary_component_entity import ComponentType


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_ptkp_status():
    """Return a valid PTKP status."""
    return EmployeePTKPStatusVO.create_single(dependents=0, effective_date=date(2024, 1, 1))


@pytest.fixture
def valid_bpjs_employment():
    """Return a valid BPJS employment enrollment."""
    return EmployeeBPJSEnrollmentVO.create_employment(
        membership_number="123456789012",
        programs=[BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT],
        enrollment_date=date(2024, 1, 1),
        risk_level=3,
    )


@pytest.fixture
def allowance_component():
    """Create an allowance salary component."""
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Transport Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("500000"),
        currency="IDR",
        is_taxable=True,
        description="Monthly transport allowance",
    )


@pytest.fixture
def deduction_component():
    """Create a deduction salary component."""
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Health Insurance",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("200000"),
        currency="IDR",
        is_taxable=False,
        description="Monthly health insurance premium",
    )


@pytest.fixture
def another_allowance():
    """Another allowance component."""
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Meal Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("300000"),
        currency="IDR",
        is_taxable=True,
        description="Meal allowance",
    )


@pytest.fixture
def salary_structure(valid_ptkp_status, valid_bpjs_employment, allowance_component, deduction_component):
    """Create a valid EmployeeSalaryStructureVO with components."""
    struct = EmployeeSalaryStructureVO.create(
        employee_id=uuid4(),
        employee_name="John Doe",
        legal_entity_id=uuid4(),
        basic_salary=Decimal("5000000"),
        currency="IDR",
        ptkp_status=valid_ptkp_status,
        bpjs_employment=valid_bpjs_employment,
        created_by="system",
    )
    # Add components
    struct = struct.add_component(allowance_component, "system")
    struct = struct.add_component(deduction_component, "system")
    return struct


# ============================================================================
# Tests for EmployeeSalaryStructureVO
# ============================================================================

class TestEmployeeSalaryStructureVOConstruction:
    def test_create(self, valid_ptkp_status, valid_bpjs_employment):
        emp_id = uuid4()
        legal_id = uuid4()
        structure = EmployeeSalaryStructureVO.create(
            employee_id=emp_id,
            employee_name="Jane Doe",
            legal_entity_id=legal_id,
            basic_salary=Decimal("7000000"),
            currency="IDR",
            ptkp_status=valid_ptkp_status,
            bpjs_employment=valid_bpjs_employment,
            created_by="hr",
        )
        assert structure.structure_id is not None
        assert structure.employee_id == emp_id
        assert structure.employee_name == "Jane Doe"
        assert structure.basic_salary == Decimal("7000000")
        assert structure.currency == "IDR"
        assert structure.salary_components == []
        assert structure.version == 1
        assert structure.created_by == "hr"

    def test_validation_basic_salary_zero(self, valid_ptkp_status, valid_bpjs_employment):
        with pytest.raises(ValueError, match="Basic salary must be positive"):
            EmployeeSalaryStructureVO.create(
                employee_id=uuid4(),
                employee_name="Test",
                legal_entity_id=uuid4(),
                basic_salary=Decimal("0"),
                currency="IDR",
                ptkp_status=valid_ptkp_status,
                bpjs_employment=valid_bpjs_employment,
            )

    def test_validation_currency_unsupported(self, valid_ptkp_status, valid_bpjs_employment):
        with pytest.raises(ValueError, match="Unsupported currency"):
            EmployeeSalaryStructureVO.create(
                employee_id=uuid4(),
                employee_name="Test",
                legal_entity_id=uuid4(),
                basic_salary=Decimal("5000000"),
                currency="XXX",
                ptkp_status=valid_ptkp_status,
                bpjs_employment=valid_bpjs_employment,
            )

    def test_validation_version(self, valid_ptkp_status, valid_bpjs_employment):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            EmployeeSalaryStructureVO(
                structure_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                legal_entity_id=uuid4(),
                basic_salary=Decimal("5000000"),
                currency="IDR",
                salary_components=[],
                ptkp_status=valid_ptkp_status,
                bpjs_employment=valid_bpjs_employment,
                version=0,
            )

    def test_validation_naive_timestamps(self, valid_ptkp_status, valid_bpjs_employment):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            EmployeeSalaryStructureVO(
                structure_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                legal_entity_id=uuid4(),
                basic_salary=Decimal("5000000"),
                currency="IDR",
                salary_components=[],
                ptkp_status=valid_ptkp_status,
                bpjs_employment=valid_bpjs_employment,
                created_at=naive,
                updated_at=naive,
            )

    def test_validation_naive_effective_date(self, valid_ptkp_status, valid_bpjs_employment):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="effective_date must be timezone-aware"):
            EmployeeSalaryStructureVO(
                structure_id=uuid4(),
                employee_id=uuid4(),
                employee_name="Test",
                legal_entity_id=uuid4(),
                basic_salary=Decimal("5000000"),
                currency="IDR",
                salary_components=[],
                ptkp_status=valid_ptkp_status,
                bpjs_employment=valid_bpjs_employment,
                effective_date=naive,
            )


class TestEmployeeSalaryStructureVOProperties:
    def test_total_allowances(self, salary_structure, allowance_component, another_allowance):
        # Initially has one allowance of 500000
        assert salary_structure.total_allowances == Decimal("500000")
        # Add another allowance
        struct = salary_structure.add_component(another_allowance, "system")
        assert struct.total_allowances == Decimal("800000")  # 500000 + 300000

    def test_total_deductions(self, salary_structure, deduction_component):
        # Initially has one deduction of 200000
        assert salary_structure.total_deductions == Decimal("200000")
        # Add another deduction
        another_deduction = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="Pension",
            component_type=ComponentType.DEDUCTION,
            amount=Decimal("100000"),
            currency="IDR",
            is_taxable=False,
            description="Pension fund",
        )
        struct = salary_structure.add_component(another_deduction, "system")
        assert struct.total_deductions == Decimal("300000")

    def test_total_salary(self, salary_structure):
        # basic_salary 5,000,000 + allowance 500,000 - deduction 200,000 = 5,300,000
        assert salary_structure.total_salary == Decimal("5300000")

    def test_bpjs_employee_contribution(self, salary_structure):
        # bpjs_employment.employee_contribution should be 0 initially because we haven't calculated
        # In our fixture, employee_contribution is 0 (since we used create_employment with no salary)
        assert salary_structure.bpjs_employee_contribution == Decimal("0")
        # We can't easily set it, but we trust the property returns the value from bpjs_employment

    def test_bpjs_employer_contribution(self, salary_structure):
        assert salary_structure.bpjs_employer_contribution == Decimal("0")


class TestEmployeeSalaryStructureVOUpdates:
    def test_add_component(self, salary_structure, another_allowance):
        old_version = salary_structure.version
        struct = salary_structure.add_component(another_allowance, "hr")
        assert len(struct.salary_components) == len(salary_structure.salary_components) + 1
        assert struct.salary_components[-1] == another_allowance
        assert struct.version == old_version + 1
        assert struct.created_by == "hr"
        assert struct.total_allowances == Decimal("800000")

    def test_remove_component(self, salary_structure, allowance_component):
        old_count = len(salary_structure.salary_components)
        comp_id = allowance_component.component_id
        struct = salary_structure.remove_component(comp_id, "hr")
        assert len(struct.salary_components) == old_count - 1
        assert comp_id not in [c.component_id for c in struct.salary_components]
        assert struct.version == salary_structure.version + 1

    def test_remove_component_not_found(self, salary_structure):
        old_count = len(salary_structure.salary_components)
        struct = salary_structure.remove_component(uuid4(), "hr")
        # Should not remove anything, but version increments anyway
        assert len(struct.salary_components) == old_count
        assert struct.version == salary_structure.version + 1

    def test_update_basic_salary(self, salary_structure):
        new_salary = Decimal("6000000")
        struct = salary_structure.update_basic_salary(new_salary, "hr")
        assert struct.basic_salary == new_salary
        assert struct.version == salary_structure.version + 1
        assert struct.created_by == "hr"

    def test_update_basic_salary_negative(self, salary_structure):
        with pytest.raises(ValueError, match="Basic salary must be positive"):
            salary_structure.update_basic_salary(Decimal("0"), "hr")

    def test_update_ptkp_status(self, salary_structure, valid_ptkp_status):
        new_ptkp = EmployeePTKPStatusVO.create_married(dependents=2)
        struct = salary_structure.update_ptkp_status(new_ptkp, "hr")
        assert struct.ptkp_status == new_ptkp
        assert struct.version == salary_structure.version + 1

    def test_update_bank_account(self, salary_structure):
        struct = salary_structure.update_bank_account(
            account_number="1234567890",
            account_name="John Doe",
            bank_code="BCA",
            updated_by="hr",
        )
        assert struct.bank_account_number == "1234567890"
        assert struct.bank_account_name == "John Doe"
        assert struct.bank_code == "BCA"
        assert struct.version == salary_structure.version + 1

    def test_update_effective_date(self, salary_structure):
        new_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        struct = salary_structure.update_effective_date(new_date, "hr")
        assert struct.effective_date == new_date
        assert struct.version == salary_structure.version + 1


class TestEmployeeSalaryStructureVOQueries:
    def test_is_active_at(self, salary_structure):
        # No effective date set, so always active
        now = datetime.now(UTC)
        assert salary_structure.is_active_at(now) is True
        assert salary_structure.is_active_at(now - timedelta(days=10)) is True
        assert salary_structure.is_active_at(now + timedelta(days=10)) is True

        # Set effective date in future
        future = now + timedelta(days=5)
        struct = salary_structure.update_effective_date(future, "system")
        assert struct.is_active_at(now) is False
        assert struct.is_active_at(future) is True
        assert struct.is_active_at(future + timedelta(days=1)) is True

    def test_get_component_by_name(self, salary_structure):
        comp = salary_structure.get_component_by_name("Transport Allowance")
        assert comp is not None
        assert comp.amount == Decimal("500000")

        # Case-insensitive
        comp2 = salary_structure.get_component_by_name("transport allowance")
        assert comp2 is not None

        # Not found
        assert salary_structure.get_component_by_name("Nonexistent") is None

    def test_get_component_by_type(self, salary_structure):
        allowances = salary_structure.get_component_by_type(ComponentType.ALLOWANCE)
        assert len(allowances) == 1
        assert allowances[0].component_name == "Transport Allowance"

        deductions = salary_structure.get_component_by_type(ComponentType.DEDUCTION)
        assert len(deductions) == 1
        assert deductions[0].component_name == "Health Insurance"

        # No such type
        no_comp = salary_structure.get_component_by_type(ComponentType.BONUS)
        assert no_comp == []


class TestEmployeeSalaryStructureVONormalize:
    def test_normalize(self, salary_structure):
        # Modify some fields to be non-normalized
        struct = salary_structure.update_bank_account(
            account_number=" 1234567890 ",
            account_name="  john doe  ",
            bank_code=" bca ",
            updated_by="system",
        )
        # Also modify employee_name
        struct = struct.update_basic_salary(Decimal("5000000"), "system")  # keep same
        # But we need a way to change employee_name - not directly, so we'll use a new instance
        # We'll create a new instance with dirty data
        dirty = EmployeeSalaryStructureVO(
            structure_id=struct.structure_id,
            employee_id=struct.employee_id,
            employee_name="  john doe  ",
            legal_entity_id=struct.legal_entity_id,
            basic_salary=Decimal("5000000.123"),
            currency=" idr ",
            salary_components=struct.salary_components,
            ptkp_status=struct.ptkp_status,
            bpjs_employment=struct.bpjs_employment,
            employee_nik=" 123456 ",
            employee_position="  engineer  ",
            bank_account_number=" 1234567890 ",
            bank_account_name="  john doe  ",
            bank_code=" bca ",
            effective_date=struct.effective_date,
            notes="  test  ",
            created_at=struct.created_at,
            updated_at=struct.updated_at,
            created_by=struct.created_by,
            version=struct.version,
        )
        normalized = dirty.normalize()
        assert normalized.employee_name == "John Doe"
        assert normalized.basic_salary == Decimal("5000000.12")  # quantized
        assert normalized.currency == "IDR"
        assert normalized.employee_nik == "123456"
        assert normalized.employee_position == "Engineer"
        assert normalized.bank_account_number == "1234567890"
        assert normalized.bank_account_name == "John Doe"
        assert normalized.bank_code == "BCA"
        assert normalized.notes == "test"
        assert normalized.version == dirty.version + 1


class TestEmployeeSalaryStructureVOSerialization:
    def test_to_dict(self, salary_structure):
        d = salary_structure.to_dict()
        assert d["structure_id"] == str(salary_structure.structure_id)
        assert d["employee_name"] == "John Doe"
        assert d["basic_salary"] == "5000000"
        assert d["currency"] == "IDR"
        assert d["total_allowances"] == "500000"
        assert d["total_deductions"] == "200000"
        assert d["total_salary"] == "5300000"
        assert "ptkp_status" in d
        assert "bpjs_employment" in d
        assert len(d["components"]) == 2
        assert d["version"] == salary_structure.version

    def test_from_dict(self, salary_structure):
        data = salary_structure.to_dict()
        # Need to reconstruct ptkp_status and bpjs_employment as dict
        data["ptkp_status"] = salary_structure.ptkp_status.to_dict()
        data["bpjs_employment"] = salary_structure.bpjs_employment.to_dict()
        restored = EmployeeSalaryStructureVO.from_dict(data)
        assert restored.structure_id == salary_structure.structure_id
        assert restored.employee_name == salary_structure.employee_name
        assert restored.basic_salary == salary_structure.basic_salary
        assert restored.currency == salary_structure.currency
        assert restored.total_allowances == salary_structure.total_allowances
        assert restored.total_deductions == salary_structure.total_deductions
        assert restored.total_salary == salary_structure.total_salary
        assert len(restored.salary_components) == len(salary_structure.salary_components)
        assert restored.ptkp_status == salary_structure.ptkp_status
        assert restored.bpjs_employment == salary_structure.bpjs_employment
        assert restored.version == salary_structure.version

    def test_from_dict_missing_fields(self):
        # Should raise KeyError if required fields missing
        with pytest.raises(KeyError):
            EmployeeSalaryStructureVO.from_dict({})

    def test_from_dict_invalid_ptkp(self):
        data = {
            "structure_id": str(uuid4()),
            "employee_id": str(uuid4()),
            "employee_name": "Test",
            "legal_entity_id": str(uuid4()),
            "basic_salary": "5000000",
            "currency": "IDR",
            "components": [],
            "ptkp_status": {"marital_status": "invalid"},  # will cause error
            "bpjs_employment": {},
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with pytest.raises(ValueError, match="Invalid marital_status"):
            EmployeeSalaryStructureVO.from_dict(data)