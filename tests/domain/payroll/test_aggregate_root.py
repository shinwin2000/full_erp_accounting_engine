# test_aggregate_root.py
# Comprehensive tests for aggregate_root.py

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.payroll.aggregate_root import PayrollAggregate, PayrollRepository
from domain.payroll.domain_events import (
    DomainEvent,
    PayrollRunApprovedEvent,
    PayrollRunCalculatedEvent,
    PayrollRunCancelledEvent,
    PayrollRunPaidEvent,
    PayrollRunPostedEvent,
)
from domain.payroll.employee_salary_structure_vo import EmployeeSalaryStructureVO
from domain.payroll.payroll_run_entity import PayrollPeriod, PayrollRunStatus
from domain.payroll.salary_component_entity import ComponentType, SalaryComponentEntity

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_class_vars():
    """Reset class variables before each test."""
    yield


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def valid_ptkp_status():
    from domain.customer_supplier_employee.employee_ptkp_status_vo import (
        EmployeePTKPStatusVO,
        MaritalStatus,
    )
    return EmployeePTKPStatusVO(
        marital_status=MaritalStatus.SINGLE,
        dependents=0,
        spouse_income_combined=False,
    )


@pytest.fixture
def valid_bpjs_employment():
    from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
        BPJSEmploymentProgram,
        BPJSType,
        EmployeeBPJSEnrollmentVO,
    )
    return EmployeeBPJSEnrollmentVO(
        bpjs_type=BPJSType.EMPLOYMENT,
        membership_number="123456789012",
        is_active=True,
        employment_programs=[BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT],
        risk_level=3,
        employee_contribution=Decimal("50000"),
        employer_contribution=Decimal("100000"),
    )


@pytest.fixture
def salary_component():
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
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Health Insurance",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("200000"),
        currency="IDR",
        is_taxable=False,
        description="Monthly health insurance",
    )


@pytest.fixture
def employee_structure(legal_entity_id, valid_ptkp_status, valid_bpjs_employment, salary_component, deduction_component):
    """Create a valid EmployeeSalaryStructureVO."""
    struct = EmployeeSalaryStructureVO.create(
        employee_id=uuid4(),
        employee_name="John Doe",
        legal_entity_id=legal_entity_id,
        basic_salary=Decimal("10000000"),
        currency="IDR",
        ptkp_status=valid_ptkp_status,
        bpjs_employment=valid_bpjs_employment,
        created_by="system",
    )
    struct = struct.add_component(salary_component, "system")
    struct = struct.add_component(deduction_component, "system")
    # Add bank account info
    struct = struct.update_bank_account(
        account_number="1234567890",
        account_name="John Doe",
        bank_code="BCA",
        updated_by="system",
    )
    return struct


@pytest.fixture
def another_employee_structure(legal_entity_id, valid_ptkp_status, valid_bpjs_employment):
    """Another employee structure."""
    struct = EmployeeSalaryStructureVO.create(
        employee_id=uuid4(),
        employee_name="Jane Smith",
        legal_entity_id=legal_entity_id,
        basic_salary=Decimal("8000000"),
        currency="IDR",
        ptkp_status=valid_ptkp_status,
        bpjs_employment=valid_bpjs_employment,
        created_by="system",
    )
    struct = struct.update_bank_account(
        account_number="0987654321",
        account_name="Jane Smith",
        bank_code="BNI",
        updated_by="system",
    )
    return struct


@pytest.fixture
def payroll_aggregate(legal_entity_id, employee_structure):
    """Create a PayrollAggregate with one employee structure."""
    agg = PayrollAggregate(
        payroll_id=uuid4(),
        legal_entity_id=legal_entity_id,
        period=PayrollPeriod.MONTHLY,
        period_year=2025,
        period_month=1,
    )
    agg = agg.add_employee_structure(employee_structure, "system")
    return agg


@pytest.fixture
def payroll_aggregate_with_run(payroll_aggregate):
    """Create a PayrollAggregate with a payroll run."""
    agg, run = payroll_aggregate.create_payroll_run(
        run_number="PR-2025-01",
        period=PayrollPeriod.MONTHLY,
        created_by="system",
    )
    # Store run_id for later use
    agg._run_id = run.run_id
    return agg


@pytest.fixture
def payroll_aggregate_with_calculated_run(payroll_aggregate_with_run):
    """Create a PayrollAggregate with a calculated payroll run."""
    agg = payroll_aggregate_with_run
    run_id = agg._run_id
    employee_ids = list(agg.employee_structures.keys())
    agg, _run = agg.calculate_payroll(run_id, employee_ids, "system")
    agg._run_id = run_id
    return agg


@pytest.fixture
def payroll_aggregate_with_approved_run(payroll_aggregate_with_calculated_run):
    """Create a PayrollAggregate with an approved payroll run."""
    agg = payroll_aggregate_with_calculated_run
    run_id = agg._run_id
    agg, _run = agg.approve_payroll(run_id, "manager")
    agg._run_id = run_id
    return agg


@pytest.fixture
def payroll_aggregate_with_paid_run(payroll_aggregate_with_approved_run):
    """Create a PayrollAggregate with a paid payroll run."""
    agg = payroll_aggregate_with_approved_run
    run_id = agg._run_id
    agg, _run = agg.process_payment(run_id, "finance")
    agg._run_id = run_id
    return agg


# ============================================================================
# Tests for PayrollAggregate - Construction and Properties
# ============================================================================

class TestPayrollAggregateConstruction:
    def test_initial_creation(self, legal_entity_id):
        agg = PayrollAggregate(
            payroll_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period=PayrollPeriod.MONTHLY,
            period_year=2025,
            period_month=1,
        )
        assert agg.payroll_id is not None
        assert agg.legal_entity_id == legal_entity_id
        assert agg.period == PayrollPeriod.MONTHLY
        assert agg.period_year == 2025
        assert agg.period_month == 1
        assert agg.payroll_runs == {}
        assert agg.employee_structures == {}
        assert agg.version == 1
        assert agg.is_locked is False

    def test_validation_period_year_invalid(self, legal_entity_id):
        with pytest.raises(ValueError, match="Invalid period year"):
            PayrollAggregate(
                payroll_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period=PayrollPeriod.MONTHLY,
                period_year=1999,
                period_month=1,
            )

    def test_validation_period_month_invalid(self, legal_entity_id):
        with pytest.raises(ValueError, match="Invalid period month"):
            PayrollAggregate(
                payroll_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=13,
            )

    def test_validation_version(self, legal_entity_id):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            PayrollAggregate(
                payroll_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=1,
                version=0,
            )

    def test_validation_naive_timestamps(self, legal_entity_id):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            PayrollAggregate(
                payroll_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period=PayrollPeriod.MONTHLY,
                period_year=2025,
                period_month=1,
                created_at=naive,
                updated_at=datetime.now(UTC),
            )

    def test_properties(self, payroll_aggregate):
        assert payroll_aggregate.id == payroll_aggregate.payroll_id
        assert payroll_aggregate.is_locked is False
        assert isinstance(payroll_aggregate.audit_trail, list)


# ============================================================================
# Tests for Event Methods
# ============================================================================

class TestEventMethods:
    def test_add_event(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate._add_event(event)
        assert len(payroll_aggregate._events) == 1
        assert payroll_aggregate._events[0] == event
        assert any(e["action"] == "event_added" for e in payroll_aggregate._audit_trail)

    def test_clear_events(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate._add_event(event)
        assert len(payroll_aggregate._events) == 1
        payroll_aggregate.clear_events()
        assert len(payroll_aggregate._events) == 0

    def test_get_events(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate._add_event(event)
        events = payroll_aggregate.get_events()
        assert len(events) == 1
        assert events is not payroll_aggregate._events

    def test_pop_events(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate._add_event(event)
        events = payroll_aggregate.pop_events()
        assert len(events) == 1
        assert len(payroll_aggregate._events) == 0

    def test_pull_events(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate._add_event(event)
        events = payroll_aggregate.pull_events()
        assert len(events) == 1
        assert len(payroll_aggregate._events) == 0

    def test_register_event(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate.register_event(event)
        assert len(payroll_aggregate._events) == 1

    def test_apply(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate.apply(event)
        assert len(payroll_aggregate._events) == 1

    def test_replay(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate.replay([event])
        assert len(payroll_aggregate._events) == 1
        assert payroll_aggregate.version == 2

    def test_reconstruct(self, payroll_aggregate):
        event = DomainEvent(
            event_type=MagicMock(),
            aggregate_id=payroll_aggregate.payroll_id,
            aggregate_version=2,
        )
        payroll_aggregate.reconstruct([event])
        assert len(payroll_aggregate._events) == 1
        assert payroll_aggregate.version == 2


# ============================================================================
# Tests for Audit Trail
# ============================================================================

class TestAuditTrail:
    def test_record_audit(self, payroll_aggregate):
        payroll_aggregate._record_audit("test_action", {"key": "value"})
        trail = payroll_aggregate.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test_action"
        assert trail[0]["details"] == {"key": "value"}
        assert trail[0]["version"] == payroll_aggregate.version

    def test_clear_audit_trail(self, payroll_aggregate):
        payroll_aggregate._record_audit("test", {})
        assert len(payroll_aggregate._audit_trail) == 1
        payroll_aggregate.clear_audit_trail()
        assert len(payroll_aggregate._audit_trail) == 0


# ============================================================================
# Tests for Snapshot
# ============================================================================

class TestSnapshot:
    def test_snapshot(self, payroll_aggregate):
        snap = payroll_aggregate.snapshot()
        assert snap["aggregate_id"] == str(payroll_aggregate.payroll_id)
        assert snap["aggregate_type"] == "PayrollAggregate"
        assert snap["version"] == payroll_aggregate.version
        assert "state" in snap
        assert snap["state"]["payroll_runs_count"] == len(payroll_aggregate.payroll_runs)
        assert snap["state"]["employee_structures_count"] == len(payroll_aggregate.employee_structures)
        assert "hash" in snap
        assert len(payroll_aggregate._snapshots) == 1

    def test_restore_from_snapshot(self, payroll_aggregate):
        snap = payroll_aggregate.snapshot()
        new_agg = PayrollAggregate(
            payroll_id=payroll_aggregate.payroll_id,
            legal_entity_id=payroll_aggregate.legal_entity_id,
            period=payroll_aggregate.period,
            period_year=payroll_aggregate.period_year,
            period_month=payroll_aggregate.period_month,
        )
        new_agg.restore_from_snapshot(snap)
        assert any(e["action"] == "restored_from_snapshot" for e in new_agg._audit_trail)

    def test_restore_from_snapshot_wrong_id(self, payroll_aggregate):
        snap = payroll_aggregate.snapshot()
        new_agg = PayrollAggregate(
            payroll_id=uuid4(),
            legal_entity_id=payroll_aggregate.legal_entity_id,
            period=payroll_aggregate.period,
            period_year=payroll_aggregate.period_year,
            period_month=payroll_aggregate.period_month,
        )
        with pytest.raises(ValueError, match="Snapshot belongs to different aggregate"):
            new_agg.restore_from_snapshot(snap)


# ============================================================================
# Tests for Lock / Unlock
# ============================================================================

class TestLockUnlock:
    def test_lock(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Reason")
        assert locked.is_locked is True
        assert locked._locked_by == "user1"
        assert locked._locked_at is not None
        assert any(e["action"] == "locked" for e in locked._audit_trail)

    def test_lock_already_locked(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Reason")
        with pytest.raises(ValueError, match="already locked"):
            locked.lock("user2", "Another")

    def test_unlock(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Reason")
        unlocked = locked.unlock("user1")
        assert unlocked.is_locked is False
        assert unlocked._locked_by is None
        assert unlocked._locked_at is None
        assert any(e["action"] == "unlocked" for e in unlocked._audit_trail)

    def test_unlock_not_locked(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not locked"):
            payroll_aggregate.unlock("user1")

    def test_unlock_wrong_user(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Reason")
        with pytest.raises(ValueError, match="locked by user1, cannot unlock by user2"):
            locked.unlock("user2")


# ============================================================================
# Tests for validate, version, touch, clone
# ============================================================================

class TestValidationAndUtils:
    def test_validate_valid(self, payroll_aggregate):
        errors = payroll_aggregate.validate()
        assert errors == []

    def test_validate_invalid(self, payroll_aggregate, employee_structure):
        # Create a structure with invalid basic salary
        invalid_structure = EmployeeSalaryStructureVO.create(
            employee_id=uuid4(),
            employee_name="Invalid",
            legal_entity_id=payroll_aggregate.legal_entity_id,
            basic_salary=Decimal("0"),
            currency="IDR",
            ptkp_status=employee_structure.ptkp_status,
            bpjs_employment=employee_structure.bpjs_employment,
        )
        agg = payroll_aggregate.add_employee_structure(invalid_structure, "system")
        errors = agg.validate()
        assert len(errors) == 1
        assert "invalid basic salary" in errors[0]

    def test_get_version(self, payroll_aggregate):
        assert payroll_aggregate.get_version() == payroll_aggregate.version

    def test_increment_version(self, payroll_aggregate):
        old_version = payroll_aggregate.version
        payroll_aggregate.increment_version()
        assert payroll_aggregate.version == old_version + 1
        assert any(e["action"] == "version_incremented" for e in payroll_aggregate._audit_trail)

    def test_touch(self, payroll_aggregate):
        payroll_aggregate.touch("user1")
        assert any(e["action"] == "touched" and e["details"]["user_id"] == "user1"
                   for e in payroll_aggregate._audit_trail)

    def test_clone(self, payroll_aggregate):
        cloned = payroll_aggregate.clone()
        assert cloned.payroll_id != payroll_aggregate.payroll_id
        assert cloned.legal_entity_id == payroll_aggregate.legal_entity_id
        assert cloned.employee_structures == payroll_aggregate.employee_structures
        assert cloned.version == 1
        assert any(e["action"] == "cloned" for e in cloned._audit_trail)


# ============================================================================
# Tests for Employee Structure Management
# ============================================================================

class TestEmployeeStructureManagement:
    def test_add_employee_structure(self, payroll_aggregate, another_employee_structure):
        old_count = len(payroll_aggregate.employee_structures)
        new_agg = payroll_aggregate.add_employee_structure(another_employee_structure, "hr")
        assert len(new_agg.employee_structures) == old_count + 1
        assert another_employee_structure.employee_id in new_agg.employee_structures
        assert new_agg.version == payroll_aggregate.version + 1
        # Check event
        events = new_agg.get_events()
        assert len(events) == 1
        # Check audit
        assert any(e["action"] == "add_employee_structure" for e in new_agg._audit_trail)

    def test_add_employee_structure_duplicate(self, payroll_aggregate, employee_structure):
        with pytest.raises(ValueError, match="already has salary structure"):
            payroll_aggregate.add_employee_structure(employee_structure, "hr")

    def test_add_employee_structure_locked(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot add structure to locked aggregate"):
            locked.add_employee_structure(MagicMock(), "hr")

    def test_update_employee_structure(self, payroll_aggregate, employee_structure):
        new_basic = Decimal("12000000")
        updated_structure = employee_structure.update_basic_salary(new_basic, "hr")
        new_agg = payroll_aggregate.update_employee_structure(updated_structure, "hr")
        assert new_agg.employee_structures[employee_structure.employee_id].basic_salary == new_basic
        assert new_agg.version == payroll_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert any(e["action"] == "update_employee_structure" for e in new_agg._audit_trail)

    def test_update_employee_structure_not_found(self, payroll_aggregate, another_employee_structure):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.update_employee_structure(another_employee_structure, "hr")

    def test_update_employee_structure_locked(self, payroll_aggregate, employee_structure):
        locked = payroll_aggregate.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot update structure in locked aggregate"):
            locked.update_employee_structure(employee_structure, "hr")

    def test_remove_employee_structure(self, payroll_aggregate, employee_structure):
        emp_id = employee_structure.employee_id
        old_count = len(payroll_aggregate.employee_structures)
        new_agg = payroll_aggregate.remove_employee_structure(emp_id, "hr")
        assert len(new_agg.employee_structures) == old_count - 1
        assert emp_id not in new_agg.employee_structures
        assert new_agg.version == payroll_aggregate.version + 1
        assert any(e["action"] == "remove_employee_structure" for e in new_agg._audit_trail)

    def test_remove_employee_structure_not_found(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.remove_employee_structure(uuid4(), "hr")

    def test_remove_employee_structure_locked(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot remove structure from locked aggregate"):
            locked.remove_employee_structure(uuid4(), "hr")

    def test_get_employee_structure(self, payroll_aggregate, employee_structure):
        struct = payroll_aggregate.get_employee_structure(employee_structure.employee_id)
        assert struct == employee_structure
        assert payroll_aggregate.get_employee_structure(uuid4()) is None


# ============================================================================
# Tests for Payroll Run Management
# ============================================================================

class TestPayrollRunManagement:
    def test_create_payroll_run(self, payroll_aggregate):
        old_count = len(payroll_aggregate.payroll_runs)
        new_agg, run = payroll_aggregate.create_payroll_run(
            run_number="PR-2025-01",
            period=PayrollPeriod.MONTHLY,
            created_by="system",
        )
        assert len(new_agg.payroll_runs) == old_count + 1
        assert run.run_id in new_agg.payroll_runs
        assert run.status == PayrollRunStatus.DRAFT
        assert new_agg.version == payroll_aggregate.version + 1
        events = new_agg.get_events()
        assert len(events) == 1
        assert any(e["action"] == "create_payroll_run" for e in new_agg._audit_trail)

    def test_create_payroll_run_locked(self, payroll_aggregate):
        locked = payroll_aggregate.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot create payroll run in locked aggregate"):
            locked.create_payroll_run("PR-001", PayrollPeriod.MONTHLY, "system")

    def test_get_payroll_run(self, payroll_aggregate_with_run):
        run_id = payroll_aggregate_with_run._run_id
        run = payroll_aggregate_with_run.get_payroll_run(run_id)
        assert run is not None
        assert run.run_id == run_id
        assert payroll_aggregate_with_run.get_payroll_run(uuid4()) is None


# ============================================================================
# Tests for Payroll Calculation
# ============================================================================

class TestPayrollCalculation:
    def test_calculate_payroll(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        run_id = agg._run_id
        employee_ids = list(agg.employee_structures.keys())
        new_agg, run = agg.calculate_payroll(run_id, employee_ids, "system")
        assert run.status == PayrollRunStatus.CALCULATED
        assert run.total_gross > 0
        assert run.total_net > 0
        assert len(run.employees) == 1
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, PayrollRunCalculatedEvent) for e in events)
        assert any(e["action"] == "calculate_payroll" for e in new_agg._audit_trail)

    def test_calculate_payroll_run_not_found(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.calculate_payroll(uuid4(), [], "system")

    def test_calculate_payroll_wrong_status(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        run_id = agg._run_id
        employee_ids = list(agg.employee_structures.keys())
        # Calculate once
        agg, _run = agg.calculate_payroll(run_id, employee_ids, "system")
        agg._run_id = run_id
        # Try to calculate again
        with pytest.raises(ValueError, match="Cannot calculate payroll in status calculated"):
            agg.calculate_payroll(run_id, employee_ids, "system")

    def test_calculate_payroll_locked(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        locked = agg.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot calculate payroll in locked aggregate"):
            locked.calculate_payroll(agg._run_id, [], "system")

    def test_calculate_payroll_employee_no_structure(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        run_id = agg._run_id
        # Use an employee ID that doesn't exist
        employee_ids = [uuid4()]
        _new_agg, run = agg.calculate_payroll(run_id, employee_ids, "system")
        # Should still calculate but with 0 employees
        assert run.status == PayrollRunStatus.CALCULATED
        assert len(run.employees) == 0


# ============================================================================
# Tests for Status Transitions
# ============================================================================

class TestStatusTransitions:
    def test_approve_payroll(self, payroll_aggregate_with_calculated_run):
        agg = payroll_aggregate_with_calculated_run
        run_id = agg._run_id
        new_agg, run = agg.approve_payroll(run_id, "manager")
        assert run.status == PayrollRunStatus.APPROVED
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, PayrollRunApprovedEvent) for e in events)
        assert any(e["action"] == "approve_payroll" for e in new_agg._audit_trail)

    def test_approve_payroll_run_not_found(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.approve_payroll(uuid4(), "manager")

    def test_approve_payroll_locked(self, payroll_aggregate_with_calculated_run):
        agg = payroll_aggregate_with_calculated_run
        locked = agg.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot approve payroll in locked aggregate"):
            locked.approve_payroll(agg._run_id, "manager")

    def test_process_payment(self, payroll_aggregate_with_approved_run):
        agg = payroll_aggregate_with_approved_run
        run_id = agg._run_id
        new_agg, run = agg.process_payment(run_id, "finance")
        assert run.status == PayrollRunStatus.PAID
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, PayrollRunPaidEvent) for e in events)
        assert any(e["action"] == "process_payment" for e in new_agg._audit_trail)

    def test_process_payment_run_not_found(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.process_payment(uuid4(), "finance")

    def test_process_payment_locked(self, payroll_aggregate_with_approved_run):
        agg = payroll_aggregate_with_approved_run
        locked = agg.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot process payment in locked aggregate"):
            locked.process_payment(agg._run_id, "finance")

    def test_cancel_payroll(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        run_id = agg._run_id
        new_agg, run = agg.cancel_payroll(run_id, "admin", "Test cancellation")
        assert run.status == PayrollRunStatus.CANCELLED
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, PayrollRunCancelledEvent) for e in events)
        assert any(e["action"] == "cancel_payroll" for e in new_agg._audit_trail)

    def test_cancel_payroll_run_not_found(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.cancel_payroll(uuid4(), "admin", "Reason")

    def test_cancel_payroll_locked(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        locked = agg.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot cancel payroll in locked aggregate"):
            locked.cancel_payroll(agg._run_id, "admin", "Reason")

    def test_post_to_gl(self, payroll_aggregate_with_paid_run):
        agg = payroll_aggregate_with_paid_run
        run_id = agg._run_id
        journal_id = uuid4()
        new_agg, _run = agg.post_to_gl(run_id, journal_id, "accountant")
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, PayrollRunPostedEvent) for e in events)
        assert any(e["action"] == "post_to_gl" for e in new_agg._audit_trail)

    def test_post_to_gl_run_not_found(self, payroll_aggregate):
        with pytest.raises(ValueError, match="not found"):
            payroll_aggregate.post_to_gl(uuid4(), uuid4(), "accountant")

    def test_post_to_gl_wrong_status(self, payroll_aggregate_with_approved_run):
        agg = payroll_aggregate_with_approved_run
        run_id = agg._run_id
        with pytest.raises(ValueError, match="Cannot post payroll in status approved"):
            agg.post_to_gl(run_id, uuid4(), "accountant")

    def test_post_to_gl_locked(self, payroll_aggregate_with_paid_run):
        agg = payroll_aggregate_with_paid_run
        locked = agg.lock("user1", "Locked")
        with pytest.raises(ValueError, match="Cannot post to GL in locked aggregate"):
            locked.post_to_gl(agg._run_id, uuid4(), "accountant")


# ============================================================================
# Tests for Query Methods
# ============================================================================

class TestQueryMethods:
    def test_get_payslip(self, payroll_aggregate_with_paid_run, employee_structure):
        agg = payroll_aggregate_with_paid_run
        run_id = agg._run_id
        emp_id = employee_structure.employee_id
        payslip = agg.get_payslip(run_id, emp_id)
        assert payslip is not None
        assert payslip.employee_id == emp_id
        assert payslip.employee_name == employee_structure.employee_name
        assert payslip.employee_nik == employee_structure.employee_nik
        assert payslip.employee_position == employee_structure.employee_position

    def test_get_payslip_run_not_found(self, payroll_aggregate):
        payslip = payroll_aggregate.get_payslip(uuid4(), uuid4())
        assert payslip is None

    def test_get_payslip_employee_not_found(self, payroll_aggregate_with_paid_run):
        agg = payroll_aggregate_with_paid_run
        payslip = agg.get_payslip(agg._run_id, uuid4())
        assert payslip is None

    def test_get_total_payroll_cost(self, payroll_aggregate_with_calculated_run):
        agg = payroll_aggregate_with_calculated_run
        run_id = agg._run_id
        total = agg.get_total_payroll_cost(run_id)
        assert total > 0
        # Should be sum of gross salaries of employees

    def test_get_total_payroll_cost_run_not_found(self, payroll_aggregate):
        total = payroll_aggregate.get_total_payroll_cost(uuid4())
        assert total == Decimal("0")

    def test_get_total_net_pay(self, payroll_aggregate_with_calculated_run):
        agg = payroll_aggregate_with_calculated_run
        run_id = agg._run_id
        total = agg.get_total_net_pay(run_id)
        assert total > 0

    def test_get_total_net_pay_run_not_found(self, payroll_aggregate):
        total = payroll_aggregate.get_total_net_pay(uuid4())
        assert total == Decimal("0")

    def test_get_payroll_runs_by_status(self, payroll_aggregate_with_calculated_run):
        agg = payroll_aggregate_with_calculated_run
        runs = agg.get_payroll_runs_by_status(PayrollRunStatus.CALCULATED)
        assert len(runs) == 1
        assert runs[0].status == PayrollRunStatus.CALCULATED
        # Should not return DRAFT runs
        runs_draft = agg.get_payroll_runs_by_status(PayrollRunStatus.DRAFT)
        assert len(runs_draft) == 0


# ============================================================================
# Tests for Serialization and Factory
# ============================================================================

class TestSerializationAndFactory:
    def test_to_dict(self, payroll_aggregate_with_run):
        agg = payroll_aggregate_with_run
        d = agg.to_dict()
        assert d["payroll_id"] == str(agg.payroll_id)
        assert d["legal_entity_id"] == str(agg.legal_entity_id)
        assert d["period"] == agg.period.value
        assert d["period_year"] == agg.period_year
        assert d["period_month"] == agg.period_month
        assert d["total_employees"] == len(agg.employee_structures)
        assert d["total_payroll_runs"] == len(agg.payroll_runs)
        assert d["version"] == agg.version
        assert d["is_locked"] is False

    def test_create(self, legal_entity_id):
        agg = PayrollAggregate.create(
            legal_entity_id=legal_entity_id,
            period=PayrollPeriod.MONTHLY,
            period_year=2025,
            period_month=1,
            created_by="system",
        )
        assert agg.legal_entity_id == legal_entity_id
        assert agg.payroll_id is not None
        assert agg.period == PayrollPeriod.MONTHLY
        assert agg.period_year == 2025
        assert agg.period_month == 1
        assert agg.version == 1
        assert agg.payroll_runs == {}
        assert agg.employee_structures == {}


# ============================================================================
# Tests for Repository (abstract)
# ============================================================================

class TestPayrollRepository:
    def test_abstract_methods_raise(self):
        repo = PayrollRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_legal_entity(uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_period(uuid4(), 2025, 1)
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4())
