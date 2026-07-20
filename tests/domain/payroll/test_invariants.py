# test_invariants.py
# Comprehensive tests for invariants.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domain.payroll.employee_salary_structure_vo import (
    EmployeeSalaryStructureVO,
    EmployeePTKPStatusVO,
)
from domain.payroll.invariants import (
    InvariantResult,
    PayrollInvariantEnforcer,
    PayrollInvariants,
    PayrollInvariantsValidator,
)
from domain.payroll.payroll_run_entity import PayrollRunEntity, PayrollRunStatus
from domain.payroll.salary_component_entity import ComponentType, SalaryComponentEntity


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_ptkp_status():
    return EmployeePTKPStatusVO.create_single(dependents=0, effective_date=date(2024, 1, 1))


@pytest.fixture
def valid_bpjs_employment():
    from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
        BPJSEmploymentProgram,
        EmployeeBPJSEnrollmentVO,
    )
    return EmployeeBPJSEnrollmentVO.create_employment(
        membership_number="123456789012",
        programs=[BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT],
        enrollment_date=date(2024, 1, 1),
        risk_level=3,
    )


@pytest.fixture
def salary_structure(valid_ptkp_status, valid_bpjs_employment):
    struct = EmployeeSalaryStructureVO.create(
        employee_id=uuid4(),
        employee_name="John Doe",
        legal_entity_id=uuid4(),
        basic_salary=Decimal("5000000"),
        currency="IDR",
        ptkp_status=valid_ptkp_status,
        bpjs_employment=valid_bpjs_employment,
    )
    # Add some components
    comp1 = SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("500000"),
        currency="IDR",
        is_taxable=True,
    )
    comp2 = SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Deduction",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("200000"),
        currency="IDR",
        is_taxable=False,
    )
    struct = struct.add_component(comp1, "system")
    struct = struct.add_component(comp2, "system")
    return struct


@pytest.fixture
def payroll_run():
    return PayrollRunEntity(
        run_id=uuid4(),
        run_number="PR-2025-01",
        legal_entity_id=uuid4(),
        period_year=2025,
        period_month=1,
        status=PayrollRunStatus.DRAFT,
        employees=[],
        total_gross=Decimal("0"),
        total_net=Decimal("0"),
        total_tax=Decimal("0"),
        total_bpjs=Decimal("0"),
        created_by="system",
    )


# ============================================================================
# Tests for InvariantResult
# ============================================================================

class TestInvariantResult:
    def test_initial_valid(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []

    def test_initial_with_errors(self):
        result = InvariantResult(False, ["error1"])
        assert result.is_valid is False
        assert result.errors == ["error1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]

    def test_merge_valid(self):
        result1 = InvariantResult()
        result2 = InvariantResult()
        result1.merge(result2)
        assert result1.is_valid is True
        assert result1.errors == []

    def test_merge_invalid(self):
        result1 = InvariantResult()
        result2 = InvariantResult(False, ["error from result2"])
        result1.merge(result2)
        assert result1.is_valid is False
        assert result1.errors == ["error from result2"]

    def test_merge_multiple_errors(self):
        result1 = InvariantResult(False, ["error1"])
        result2 = InvariantResult(False, ["error2", "error3"])
        result1.merge(result2)
        assert result1.is_valid is False
        assert result1.errors == ["error1", "error2", "error3"]

    def test_to_dict(self):
        result = InvariantResult(False, ["error1", "error2"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["error1", "error2"]
        assert d["error_count"] == 2

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(False, ["error"])) is False


# ============================================================================
# Tests for PayrollInvariants (Static Methods)
# ============================================================================

class TestPayrollInvariants:
    def test_validate_basic_salary_valid(self):
        result = PayrollInvariants.validate_basic_salary(Decimal("5000000"))
        assert result.is_valid is True
        assert result.errors == []

    def test_validate_basic_salary_zero(self):
        result = PayrollInvariants.validate_basic_salary(Decimal("0"))
        assert result.is_valid is False
        assert "Basic salary must be positive" in result.errors[0]

    def test_validate_basic_salary_negative(self):
        result = PayrollInvariants.validate_basic_salary(Decimal("-100"))
        assert result.is_valid is False
        assert "Basic salary must be positive" in result.errors[0]

    def test_validate_basic_salary_below_umr(self):
        result = PayrollInvariants.validate_basic_salary(
            Decimal("3000000"), regional_minimum_wage=Decimal("4500000")
        )
        assert result.is_valid is False
        assert "below regional minimum wage" in result.errors[0]

    def test_validate_basic_salary_with_umr_and_valid(self):
        result = PayrollInvariants.validate_basic_salary(
            Decimal("5000000"), regional_minimum_wage=Decimal("4500000")
        )
        assert result.is_valid is True

    def test_validate_net_salary_valid(self):
        result = PayrollInvariants.validate_net_salary(Decimal("1000000"))
        assert result.is_valid is True

    def test_validate_net_salary_negative(self):
        result = PayrollInvariants.validate_net_salary(Decimal("-100"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_tax_calculation_valid(self):
        gross = Decimal("1000000")
        tax = Decimal("200000")
        net = Decimal("800000")
        result = PayrollInvariants.validate_tax_calculation(gross, tax, net)
        assert result.is_valid is True

    def test_validate_tax_calculation_negative_tax(self):
        result = PayrollInvariants.validate_tax_calculation(
            Decimal("1000000"), Decimal("-100"), Decimal("1000100")
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_tax_calculation_tax_exceeds_gross(self):
        result = PayrollInvariants.validate_tax_calculation(
            Decimal("1000000"), Decimal("1500000"), Decimal("-500000")
        )
        assert result.is_valid is False
        assert "Tax 1500000 exceeds gross salary 1000000" in result.errors[0]

    def test_validate_tax_calculation_net_mismatch(self):
        result = PayrollInvariants.validate_tax_calculation(
            Decimal("1000000"), Decimal("200000"), Decimal("700000")
        )
        assert result.is_valid is False
        assert "Net salary mismatch" in result.errors[0]

    def test_validate_employee_structure_valid(self, salary_structure):
        result = PayrollInvariants.validate_employee_structure(salary_structure)
        assert result.is_valid is True

    def test_validate_employee_structure_duplicate_component_names(self, salary_structure):
        # Add a duplicate component name
        duplicate = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="Allowance",
            component_type=ComponentType.ALLOWANCE,
            amount=Decimal("100000"),
            currency="IDR",
            is_taxable=True,
        )
        struct = salary_structure.add_component(duplicate, "system")
        result = PayrollInvariants.validate_employee_structure(struct)
        assert result.is_valid is False
        assert "Duplicate component name: Allowance" in result.errors[0]

    def test_validate_employee_structure_negative_total_salary(self, salary_structure):
        # Create a structure with huge deduction making total negative
        big_deduction = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="Big Deduction",
            component_type=ComponentType.DEDUCTION,
            amount=Decimal("6000000"),
            currency="IDR",
            is_taxable=False,
        )
        struct = salary_structure.add_component(big_deduction, "system")
        result = PayrollInvariants.validate_employee_structure(struct)
        assert result.is_valid is False
        assert "Total salary cannot be negative" in result.errors[0]

    def test_validate_payroll_run_status_transition_valid(self):
        transitions = [
            (PayrollRunStatus.DRAFT, PayrollRunStatus.CALCULATED),
            (PayrollRunStatus.DRAFT, PayrollRunStatus.CANCELLED),
            (PayrollRunStatus.CALCULATED, PayrollRunStatus.APPROVED),
            (PayrollRunStatus.CALCULATED, PayrollRunStatus.CANCELLED),
            (PayrollRunStatus.APPROVED, PayrollRunStatus.PAID),
            (PayrollRunStatus.APPROVED, PayrollRunStatus.CANCELLED),
        ]
        for current, new in transitions:
            result = PayrollInvariants.validate_payroll_run_status_transition(current, new)
            assert result.is_valid is True, f"Failed for {current.value} -> {new.value}"

    def test_validate_payroll_run_status_transition_invalid(self):
        invalid = [
            (PayrollRunStatus.DRAFT, PayrollRunStatus.PAID),
            (PayrollRunStatus.CALCULATED, PayrollRunStatus.DRAFT),
            (PayrollRunStatus.APPROVED, PayrollRunStatus.DRAFT),
            (PayrollRunStatus.PAID, PayrollRunStatus.APPROVED),
            (PayrollRunStatus.CANCELLED, PayrollRunStatus.DRAFT),
        ]
        for current, new in invalid:
            result = PayrollInvariants.validate_payroll_run_status_transition(current, new)
            assert result.is_valid is False, f"Should be invalid: {current.value} -> {new.value}"
            assert "Invalid status transition" in result.errors[0]

    def test_validate_payment_amount_valid(self):
        result = PayrollInvariants.validate_payment_amount(
            Decimal("1000000"), Decimal("1000000")
        )
        assert result.is_valid is True

    def test_validate_payment_amount_invalid(self):
        result = PayrollInvariants.validate_payment_amount(
            Decimal("1000000"), Decimal("900000")
        )
        assert result.is_valid is False
        assert "Payment amount 900000 does not match total net pay 1000000" in result.errors[0]

    def test_validate_period_uniqueness_no_existing(self):
        result = PayrollInvariants.validate_period_uniqueness(2025, 1, [])
        assert result.is_valid is True

    def test_validate_period_uniqueness_no_conflict(self, payroll_run):
        # Different period
        existing = [payroll_run]  # period 2025/1
        result = PayrollInvariants.validate_period_uniqueness(2025, 2, existing)
        assert result.is_valid is True

    def test_validate_period_uniqueness_conflict(self, payroll_run):
        existing = [payroll_run]  # period 2025/1
        result = PayrollInvariants.validate_period_uniqueness(2025, 1, existing)
        assert result.is_valid is False
        assert "Payroll run already exists for 1/2025" in result.errors[0]

    def test_validate_period_uniqueness_ignores_cancelled(self, payroll_run):
        # A cancelled run should not block new run
        cancelled_run = PayrollRunEntity(
            run_id=uuid4(),
            run_number="PR-2025-01-C",
            legal_entity_id=uuid4(),
            period_year=2025,
            period_month=1,
            status=PayrollRunStatus.CANCELLED,
            employees=[],
            total_gross=Decimal("0"),
            total_net=Decimal("0"),
            total_tax=Decimal("0"),
            total_bpjs=Decimal("0"),
            created_by="system",
        )
        result = PayrollInvariants.validate_period_uniqueness(2025, 1, [cancelled_run])
        assert result.is_valid is True


# ============================================================================
# Tests for PayrollInvariantEnforcer
# ============================================================================

class TestPayrollInvariantEnforcer:
    async def test_enforce_salary_structure(self, salary_structure):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_salary_structure(salary_structure)
        assert result.is_valid is True

    async def test_enforce_salary_structure_with_umr_checker(self, salary_structure):
        async def umr_checker(legal_entity_id, effective_date):
            return Decimal("4500000")

        enforcer = PayrollInvariantEnforcer(umr_checker=umr_checker)
        # basic_salary is 5000000, so valid
        result = await enforcer.enforce_salary_structure(salary_structure)
        assert result.is_valid is True

    async def test_enforce_salary_structure_with_umr_checker_below(self, salary_structure):
        async def umr_checker(legal_entity_id, effective_date):
            return Decimal("5500000")

        enforcer = PayrollInvariantEnforcer(umr_checker=umr_checker)
        result = await enforcer.enforce_salary_structure(salary_structure)
        assert result.is_valid is False
        assert "below regional minimum wage" in result.errors[0]

    async def test_enforce_salary_structure_umr_checker_raises(self, salary_structure):
        async def umr_checker(*args, **kwargs):
            raise Exception("UMR service unavailable")

        enforcer = PayrollInvariantEnforcer(umr_checker=umr_checker)
        result = await enforcer.enforce_salary_structure(salary_structure)
        # Should still validate basic salary without UMR
        assert result.is_valid is True

    async def test_enforce_payroll_calculation_valid(self):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_payroll_calculation(
            gross_salary=Decimal("1000000"),
            tax=Decimal("200000"),
            net_salary=Decimal("800000"),
        )
        assert result.is_valid is True

    async def test_enforce_payroll_calculation_invalid(self):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_payroll_calculation(
            gross_salary=Decimal("1000000"),
            tax=Decimal("1500000"),
            net_salary=Decimal("-500000"),
        )
        assert result.is_valid is False
        assert len(result.errors) >= 1

    async def test_enforce_status_transition_valid(self):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_status_transition(
            PayrollRunStatus.DRAFT, PayrollRunStatus.CALCULATED
        )
        assert result.is_valid is True

    async def test_enforce_status_transition_invalid(self):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_status_transition(
            PayrollRunStatus.DRAFT, PayrollRunStatus.PAID
        )
        assert result.is_valid is False

    async def test_enforce_payment_valid(self):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_payment(
            total_net=Decimal("1000000"), payment_amount=Decimal("1000000")
        )
        assert result.is_valid is True

    async def test_enforce_payment_invalid(self):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_payment(
            total_net=Decimal("1000000"), payment_amount=Decimal("900000")
        )
        assert result.is_valid is False

    async def test_enforce_period_uniqueness_valid(self, payroll_run):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_period_uniqueness(2025, 1, [])
        assert result.is_valid is True

    async def test_enforce_period_uniqueness_conflict(self, payroll_run):
        enforcer = PayrollInvariantEnforcer()
        result = await enforcer.enforce_period_uniqueness(2025, 1, [payroll_run])
        assert result.is_valid is False


# ============================================================================
# Tests for PayrollInvariantsValidator (Compatibility class)
# ============================================================================

class TestPayrollInvariantsValidator:
    def test_validate_basic_salary_valid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_basic_salary(Decimal("5000000"))
        assert result.is_valid is True

    def test_validate_basic_salary_invalid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_basic_salary(Decimal("-100"))
        assert result.is_valid is False

    def test_validate_net_salary_valid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_net_salary(Decimal("1000000"))
        assert result.is_valid is True

    def test_validate_net_salary_invalid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_net_salary(Decimal("-100"))
        assert result.is_valid is False

    def test_validate_tax_calculation_valid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_tax_calculation(
            Decimal("1000000"), Decimal("200000"), Decimal("800000")
        )
        assert result.is_valid is True

    def test_validate_tax_calculation_invalid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_tax_calculation(
            Decimal("1000000"), Decimal("1500000"), Decimal("-500000")
        )
        assert result.is_valid is False

    def test_validate_employee_structure_valid(self, salary_structure):
        validator = PayrollInvariantsValidator()
        result = validator.validate_employee_structure(salary_structure)
        assert result.is_valid is True

    def test_validate_employee_structure_invalid(self, salary_structure):
        # Add duplicate component
        duplicate = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="Allowance",
            component_type=ComponentType.ALLOWANCE,
            amount=Decimal("100000"),
            currency="IDR",
            is_taxable=True,
        )
        struct = salary_structure.add_component(duplicate, "system")
        validator = PayrollInvariantsValidator()
        result = validator.validate_employee_structure(struct)
        assert result.is_valid is False

    def test_validate_status_transition_valid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_status_transition(
            PayrollRunStatus.DRAFT, PayrollRunStatus.CALCULATED
        )
        assert result.is_valid is True

    def test_validate_status_transition_invalid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_status_transition(
            PayrollRunStatus.DRAFT, PayrollRunStatus.PAID
        )
        assert result.is_valid is False

    def test_validate_payment_amount_valid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_payment_amount(
            Decimal("1000000"), Decimal("1000000")
        )
        assert result.is_valid is True

    def test_validate_payment_amount_invalid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_payment_amount(
            Decimal("1000000"), Decimal("900000")
        )
        assert result.is_valid is False

    def test_validate_period_uniqueness_valid(self):
        validator = PayrollInvariantsValidator()
        result = validator.validate_period_uniqueness(2025, 1, [])
        assert result.is_valid is True

    def test_validate_period_uniqueness_conflict(self, payroll_run):
        validator = PayrollInvariantsValidator()
        result = validator.validate_period_uniqueness(2025, 1, [payroll_run])
        assert result.is_valid is False