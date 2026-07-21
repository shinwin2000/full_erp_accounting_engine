#!/usr/bin/env python3
"""
Comprehensive tests for Employee Aggregate Root.

Covers:
- All custom exceptions
- All aggregate methods (CRUD, workflow, queries, commands)
- All repository methods
- Domain events
- Edge cases and negative paths
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.customer_supplier_employee.domain_events import (
    EmployeeBPJSUpdatedEvent,
    EmployeeCreatedEvent,
    EmployeePTKPUpdatedEvent,
    EmployeeResignedEvent,
)
from domain.customer_supplier_employee.employee_aggregate_root import (
    DuplicateEmailError,
    DuplicateEmployeeNumberError,
    DuplicateTaxIdError,
    EmployeeAggregate,
    EmployeeAggregateError,
    EmployeeAggregateRepository,
    EmployeeNotFoundError,
    InvalidEmployeeStatusTransitionError,
    _validate_email_unique,
    _validate_employee_number_unique,
    _validate_status_transition,
    _validate_tax_id_unique,
)
from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
    EmployeeBPJSEnrollmentVO,
)
from domain.customer_supplier_employee.employee_entity import (
    EmployeeEntity,
    EmployeeStatus,
    EmployeeType,
    Gender,
)
from domain.customer_supplier_employee.employee_ptkp_status_vo import (
    EmployeePTKPStatusVO,
    PTKPStatus,
)


# =============================================================================
# Helper factories
# =============================================================================

def create_valid_employee(
    employee_id: UUID | None = None,
    employee_number: str = "EMP-001",
    full_name: str = "John Doe",
    email: str = "john@example.com",
    tax_id: str = "1234567890",
    status: EmployeeStatus = EmployeeStatus.DRAFT,
    employee_type: EmployeeType = EmployeeType.FULL_TIME,
    gender: Gender = Gender.MALE,
    basic_salary: Decimal = Decimal("5000000"),
    department: str = "IT",
    position: str = "Developer",
    version: int = 1,
    **kwargs,
) -> EmployeeEntity:
    """Create a valid EmployeeEntity for testing."""
    return EmployeeEntity(
        employee_id=employee_id or uuid4(),
        legal_entity_id=uuid4(),
        employee_number=employee_number,
        full_name=full_name,
        email=email,
        tax_id=tax_id,
        status=status,
        employee_type=employee_type,
        gender=gender,
        basic_salary=basic_salary,
        department=department,
        position=position,
        birth_date=date(1990, 1, 1),
        join_date=date(2020, 1, 1),
        version=version,
        **kwargs,
    )


def create_valid_ptkp() -> EmployeePTKPStatusVO:
    return EmployeePTKPStatusVO(
        status=PTKPStatus.TK0,
        dependents=0,
        effective_date=date.today(),
        tax_regulation="PPH21",
    )


def create_valid_bpjs_health() -> EmployeeBPJSEnrollmentVO:
    return EmployeeBPJSEnrollmentVO(
        membership_number="BPJS-001",
        is_active=True,
        enrollment_date=date.today(),
        provider="BPJS Kesehatan",
        notes="Active",
    )


def create_valid_bpjs_employment() -> EmployeeBPJSEnrollmentVO:
    return EmployeeBPJSEnrollmentVO(
        membership_number="BPJS-002",
        is_active=True,
        enrollment_date=date.today(),
        provider="BPJS Ketenagakerjaan",
        notes="Active",
    )


@pytest.fixture
def empty_aggregate() -> EmployeeAggregate:
    return EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")


@pytest.fixture
def aggregate_with_employee(empty_aggregate) -> EmployeeAggregate:
    emp = create_valid_employee()
    return empty_aggregate.add_employee(emp, "tester")


@pytest.fixture
def active_employee_aggregate() -> EmployeeAggregate:
    agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
    emp = create_valid_employee(status=EmployeeStatus.ACTIVE)
    return agg.add_employee(emp, "tester")


# =============================================================================
# Exception tests
# =============================================================================

class TestExceptions:
    def test_employee_aggregate_error(self):
        with pytest.raises(EmployeeAggregateError):
            raise EmployeeAggregateError("test")

    def test_duplicate_employee_number_error(self):
        with pytest.raises(DuplicateEmployeeNumberError):
            raise DuplicateEmployeeNumberError("duplicate")

    def test_duplicate_email_error(self):
        with pytest.raises(DuplicateEmailError):
            raise DuplicateEmailError("duplicate email")

    def test_duplicate_tax_id_error(self):
        with pytest.raises(DuplicateTaxIdError):
            raise DuplicateTaxIdError("duplicate tax id")

    def test_employee_not_found_error(self):
        with pytest.raises(EmployeeNotFoundError):
            raise EmployeeNotFoundError("not found")

    def test_invalid_status_transition_error(self):
        with pytest.raises(InvalidEmployeeStatusTransitionError):
            raise InvalidEmployeeStatusTransitionError("invalid")


# =============================================================================
# Helper validation function tests
# =============================================================================

class TestValidationHelpers:
    def test_validate_employee_number_unique_passes(self):
        existing = {"EMP-001": uuid4(), "EMP-002": uuid4()}
        # Should not raise
        _validate_employee_number_unique("EMP-003", set(existing.keys()))

    def test_validate_employee_number_unique_raises(self):
        existing = {"EMP-001": uuid4()}
        with pytest.raises(DuplicateEmployeeNumberError, match="already exists"):
            _validate_employee_number_unique("EMP-001", set(existing.keys()))

    def test_validate_email_unique_passes(self):
        existing = {"a@b.com": uuid4()}
        _validate_email_unique("c@d.com", existing)

    def test_validate_email_unique_raises(self):
        emp_id = uuid4()
        existing = {"a@b.com": emp_id}
        with pytest.raises(DuplicateEmailError, match="already exists"):
            _validate_email_unique("a@b.com", existing, exclude_id=uuid4())

    def test_validate_email_unique_exclude_self(self):
        emp_id = uuid4()
        existing = {"a@b.com": emp_id}
        # Should not raise because we're excluding the same id
        _validate_email_unique("a@b.com", existing, exclude_id=emp_id)

    def test_validate_tax_id_unique_passes(self):
        existing = {"123": uuid4()}
        _validate_tax_id_unique("456", existing)

    def test_validate_tax_id_unique_raises(self):
        emp_id = uuid4()
        existing = {"123": emp_id}
        with pytest.raises(DuplicateTaxIdError, match="already exists"):
            _validate_tax_id_unique("123", existing, exclude_id=uuid4())

    def test_validate_tax_id_unique_exclude_self(self):
        emp_id = uuid4()
        existing = {"123": emp_id}
        _validate_tax_id_unique("123", existing, exclude_id=emp_id)

    def test_validate_status_transition_valid(self):
        _validate_status_transition(EmployeeStatus.DRAFT, EmployeeStatus.ACTIVE)
        _validate_status_transition(EmployeeStatus.ACTIVE, EmployeeStatus.ON_LEAVE)
        _validate_status_transition(EmployeeStatus.ON_LEAVE, EmployeeStatus.ACTIVE)

    def test_validate_status_transition_invalid(self):
        with pytest.raises(InvalidEmployeeStatusTransitionError):
            _validate_status_transition(EmployeeStatus.RESIGNED, EmployeeStatus.ACTIVE)
        with pytest.raises(InvalidEmployeeStatusTransitionError):
            _validate_status_transition(EmployeeStatus.DRAFT, EmployeeStatus.RESIGNED)


# =============================================================================
# EmployeeAggregate tests
# =============================================================================

class TestEmployeeAggregate:
    def test_create_factory(self):
        legal_entity_id = uuid4()
        agg = EmployeeAggregate.create(legal_entity_id, "creator")
        assert agg.aggregate_id is not None
        assert agg.legal_entity_id == legal_entity_id
        assert agg.version == 1
        assert len(agg.employees) == 0
        assert len(agg._audit_trail) == 1
        assert agg._audit_trail[0]["action"] == "CREATE"

    def test_add_employee_success(self, empty_aggregate):
        emp = create_valid_employee()
        agg = empty_aggregate.add_employee(emp, "tester")
        assert len(agg.employees) == 1
        assert agg.employee_by_number[emp.employee_number] == emp.employee_id
        assert agg.employee_by_email[emp.email] == emp.employee_id
        assert agg.employee_by_tax_id[emp.tax_id] == emp.employee_id
        assert agg.version == 2
        # Check event was registered
        events = agg.get_events()
        assert len(events) == 1
        assert isinstance(events[0], EmployeeCreatedEvent)
        assert events[0].employee == emp
        assert events[0].created_by == "tester"

    def test_add_employee_duplicate_number_raises(self, empty_aggregate):
        emp1 = create_valid_employee(employee_number="EMP-001")
        agg = empty_aggregate.add_employee(emp1, "tester")
        emp2 = create_valid_employee(employee_number="EMP-001", email="other@example.com")
        with pytest.raises(DuplicateEmployeeNumberError):
            agg.add_employee(emp2, "tester")

    def test_add_employee_duplicate_email_raises(self, empty_aggregate):
        emp1 = create_valid_employee(email="same@example.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        emp2 = create_valid_employee(employee_number="EMP-002", email="same@example.com")
        with pytest.raises(DuplicateEmailError):
            agg.add_employee(emp2, "tester")

    def test_add_employee_duplicate_tax_id_raises(self, empty_aggregate):
        emp1 = create_valid_employee(tax_id="1234567890")
        agg = empty_aggregate.add_employee(emp1, "tester")
        emp2 = create_valid_employee(employee_number="EMP-002", email="other@example.com", tax_id="1234567890")
        with pytest.raises(DuplicateTaxIdError):
            agg.add_employee(emp2, "tester")

    def test_get_employee(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        found = aggregate_with_employee.get_employee(emp.employee_id)
        assert found == emp

    def test_get_employee_by_number(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        found = aggregate_with_employee.get_employee_by_number(emp.employee_number)
        assert found == emp

    def test_get_employee_by_email(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        found = aggregate_with_employee.get_employee_by_email(emp.email)
        assert found == emp

    def test_get_employee_by_tax_id(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        found = aggregate_with_employee.get_employee_by_tax_id(emp.tax_id)
        assert found == emp

    def test_get_all_employees(self, aggregate_with_employee):
        all_emps = aggregate_with_employee.get_all_employees()
        assert len(all_emps) == 1

    def test_get_active_employees(self, empty_aggregate):
        emp_active = create_valid_employee(status=EmployeeStatus.ACTIVE)
        emp_inactive = create_valid_employee(employee_number="EMP-002", status=EmployeeStatus.INACTIVE, email="i@b.com")
        agg = empty_aggregate.add_employee(emp_active, "tester")
        agg = agg.add_employee(emp_inactive, "tester")
        active = agg.get_active_employees()
        assert len(active) == 1
        assert active[0].status == EmployeeStatus.ACTIVE

    def test_get_employees_by_status(self, empty_aggregate):
        emp1 = create_valid_employee(status=EmployeeStatus.ACTIVE)
        emp2 = create_valid_employee(employee_number="EMP-002", status=EmployeeStatus.ON_LEAVE, email="x@y.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        on_leave = agg.get_employees_by_status(EmployeeStatus.ON_LEAVE)
        assert len(on_leave) == 1
        assert on_leave[0].status == EmployeeStatus.ON_LEAVE

    def test_get_employees_by_type(self, empty_aggregate):
        emp1 = create_valid_employee(employee_type=EmployeeType.FULL_TIME)
        emp2 = create_valid_employee(employee_number="EMP-002", employee_type=EmployeeType.PART_TIME, email="x@y.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        part_time = agg.get_employees_by_type(EmployeeType.PART_TIME)
        assert len(part_time) == 1

    def test_get_employees_by_department(self, empty_aggregate):
        emp1 = create_valid_employee(department="IT")
        emp2 = create_valid_employee(employee_number="EMP-002", department="HR", email="x@y.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        hr = agg.get_employees_by_department("HR")
        assert len(hr) == 1

    def test_get_employees_by_gender(self, empty_aggregate):
        emp1 = create_valid_employee(gender=Gender.MALE)
        emp2 = create_valid_employee(employee_number="EMP-002", gender=Gender.FEMALE, email="x@y.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        females = agg.get_employees_by_gender(Gender.FEMALE)
        assert len(females) == 1

    def test_get_total_active_employees(self, empty_aggregate):
        emp_active = create_valid_employee(status=EmployeeStatus.ACTIVE)
        emp_inactive = create_valid_employee(employee_number="EMP-002", status=EmployeeStatus.INACTIVE, email="x@y.com")
        agg = empty_aggregate.add_employee(emp_active, "tester")
        agg = agg.add_employee(emp_inactive, "tester")
        assert agg.get_total_active_employees() == 1

    def test_get_total_employees(self, empty_aggregate):
        emp1 = create_valid_employee()
        emp2 = create_valid_employee(employee_number="EMP-002", email="x@y.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        assert agg.get_total_employees() == 2

    def test_get_total_monthly_salary_bill(self, empty_aggregate):
        emp1 = create_valid_employee(basic_salary=Decimal("5000000"), status=EmployeeStatus.ACTIVE)
        emp2 = create_valid_employee(employee_number="EMP-002", basic_salary=Decimal("7000000"), status=EmployeeStatus.ACTIVE, email="x@y.com")
        emp3 = create_valid_employee(employee_number="EMP-003", basic_salary=Decimal("3000000"), status=EmployeeStatus.INACTIVE, email="z@w.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        agg = agg.add_employee(emp3, "tester")
        total = agg.get_total_monthly_salary_bill()
        assert total == Decimal("12000000")  # 5jt + 7jt, inactive excluded

    def test_number_exists(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        assert aggregate_with_employee.number_exists(emp.employee_number) is True
        assert aggregate_with_employee.number_exists("NONEXISTENT") is False

    def test_email_exists(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        assert aggregate_with_employee.email_exists(emp.email) is True
        assert aggregate_with_employee.email_exists("fake@example.com") is False

    def test_tax_id_exists(self, aggregate_with_employee):
        emp = list(aggregate_with_employee.employees.values())[0]
        assert aggregate_with_employee.tax_id_exists(emp.tax_id) is True
        assert aggregate_with_employee.tax_id_exists("000000") is False

    def test_update_employee_success(self, aggregate_with_employee):
        old_emp = list(aggregate_with_employee.employees.values())[0]
        new_emp = EmployeeEntity(
            employee_id=old_emp.employee_id,
            legal_entity_id=old_emp.legal_entity_id,
            employee_number=old_emp.employee_number,
            full_name="Updated Name",
            email=old_emp.email,
            tax_id=old_emp.tax_id,
            status=old_emp.status,
            employee_type=old_emp.employee_type,
            gender=old_emp.gender,
            basic_salary=Decimal("6000000"),
            department=old_emp.department,
            position=old_emp.position,
            birth_date=old_emp.birth_date,
            join_date=old_emp.join_date,
            version=old_emp.version + 1,
        )
        agg = aggregate_with_employee.update_employee(new_emp, "updater")
        assert agg.version == 3  # initial add (2) + update
        updated = agg.get_employee(old_emp.employee_id)
        assert updated.full_name == "Updated Name"
        assert updated.basic_salary == Decimal("6000000")

    def test_update_employee_not_found(self, aggregate_with_employee):
        emp = create_valid_employee()
        with pytest.raises(EmployeeNotFoundError):
            aggregate_with_employee.update_employee(emp, "updater")

    def test_update_employee_version_mismatch(self, aggregate_with_employee):
        old_emp = list(aggregate_with_employee.employees.values())[0]
        new_emp = EmployeeEntity(
            employee_id=old_emp.employee_id,
            legal_entity_id=old_emp.legal_entity_id,
            employee_number=old_emp.employee_number,
            full_name="New",
            email=old_emp.email,
            tax_id=old_emp.tax_id,
            status=old_emp.status,
            employee_type=old_emp.employee_type,
            gender=old_emp.gender,
            basic_salary=Decimal("6000000"),
            department=old_emp.department,
            position=old_emp.position,
            birth_date=old_emp.birth_date,
            join_date=old_emp.join_date,
            version=old_emp.version,  # same version
        )
        with pytest.raises(ValueError, match="Version mismatch"):
            aggregate_with_employee.update_employee(new_emp, "updater")

    def test_update_employee_status_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr", "Activated")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.ACTIVE
        assert agg.version == 3

    def test_update_employee_status_invalid_transition(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        # From DRAFT to RESIGNED is invalid
        with pytest.raises(InvalidEmployeeStatusTransitionError):
            aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.RESIGNED, "hr", "Invalid")

    def test_update_employee_status_not_found(self, empty_aggregate):
        with pytest.raises(EmployeeNotFoundError):
            empty_aggregate.update_employee_status(uuid4(), EmployeeStatus.ACTIVE, "hr")

    def test_update_employee_status_resigned_triggers_event(self, aggregate_with_employee):
        # First set to ACTIVE
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        # Then resign
        agg = agg.update_employee_status(emp_id, EmployeeStatus.RESIGNED, "hr", "Resigning")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.RESIGNED
        events = agg.get_events()
        # There should be at least 3 events: create, status change to active, resign
        resign_events = [e for e in events if isinstance(e, EmployeeResignedEvent)]
        assert len(resign_events) == 1
        assert resign_events[0].reason == "Resigning"

    def test_update_employee_ptkp(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        new_ptkp = create_valid_ptkp()
        agg = aggregate_with_employee.update_employee_ptkp(emp_id, new_ptkp, "hr")
        updated = agg.get_employee(emp_id)
        assert updated.ptkp_status == new_ptkp
        events = agg.get_events()
        assert any(isinstance(e, EmployeePTKPUpdatedEvent) for e in events)

    def test_update_employee_bpjs_health(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        bpjs = create_valid_bpjs_health()
        agg = aggregate_with_employee.update_employee_bpjs_health(emp_id, bpjs, "hr")
        updated = agg.get_employee(emp_id)
        assert updated.bpjs_health == bpjs
        events = agg.get_events()
        assert any(isinstance(e, EmployeeBPJSUpdatedEvent) and e.bpjs_type == "health" for e in events)

    def test_update_employee_bpjs_employment(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        bpjs = create_valid_bpjs_employment()
        agg = aggregate_with_employee.update_employee_bpjs_employment(emp_id, bpjs, "hr")
        updated = agg.get_employee(emp_id)
        assert updated.bpjs_employment == bpjs
        events = agg.get_events()
        assert any(isinstance(e, EmployeeBPJSUpdatedEvent) and e.bpjs_type == "employment" for e in events)

    def test_update_employee_salary(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        new_salary = Decimal("8000000")
        agg = aggregate_with_employee.update_employee_salary(emp_id, new_salary, "hr", date.today())
        updated = agg.get_employee(emp_id)
        assert updated.basic_salary == new_salary

    def test_update_employee_department(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_department(emp_id, "Finance", "hr")
        updated = agg.get_employee(emp_id)
        assert updated.department == "Finance"

    def test_update_employee_position(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_position(emp_id, "Senior Developer", "hr")
        updated = agg.get_employee(emp_id)
        assert updated.position == "Senior Developer"

    def test_remove_employee_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.remove_employee(emp_id, "admin")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.INACTIVE
        assert agg.version == 3

    def test_remove_employee_not_found(self, empty_aggregate):
        with pytest.raises(EmployeeNotFoundError):
            empty_aggregate.remove_employee(uuid4(), "admin")

    def test_remove_employee_resigned_raises(self, aggregate_with_employee):
        # First set to active then resign
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        agg = agg.update_employee_status(emp_id, EmployeeStatus.RESIGNED, "hr", "resign")
        with pytest.raises(EmployeeAggregateError, match="Cannot remove employee with status Resigned"):
            agg.remove_employee(emp_id, "admin")

    def test_can_post(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        assert aggregate_with_employee.can_post(emp_id) is False  # DRAFT
        # Activate
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        assert agg.can_post(emp_id) is True

    def test_post(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        new_salary = Decimal("6000000")
        agg = agg.post(emp_id, new_salary, "payroll", "salary")
        updated = agg.get_employee(emp_id)
        assert updated.basic_salary == new_salary

    def test_post_unknown_type(self, aggregate_with_employee):
        with pytest.raises(ValueError, match="Unknown transaction type"):
            aggregate_with_employee.post(uuid4(), Decimal("1000"), "user", "unknown")

    def test_can_approve(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        assert aggregate_with_employee.can_approve(emp_id, "hr_manager") is True
        assert aggregate_with_employee.can_approve(emp_id, "user") is False

    def test_approve_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.approve(emp_id, "hr_manager")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.ACTIVE

    def test_approve_not_allowed(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        with pytest.raises(EmployeeAggregateError):
            aggregate_with_employee.approve(emp_id, "user")

    def test_can_reject(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        assert aggregate_with_employee.can_reject(emp_id, "hr_manager") is True
        assert aggregate_with_employee.can_reject(emp_id, "user") is False

    def test_reject_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.reject(emp_id, "hr_manager", "Not qualified")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.INACTIVE

    def test_reject_not_allowed(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        with pytest.raises(EmployeeAggregateError):
            aggregate_with_employee.reject(emp_id, "user", "No")

    def test_can_cancel(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        assert aggregate_with_employee.can_cancel(emp_id) is True
        # After activating, can_cancel should be False
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        assert agg.can_cancel(emp_id) is False

    def test_cancel_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.cancel(emp_id, "hr", "No longer needed")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.INACTIVE

    def test_cancel_not_allowed(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        with pytest.raises(EmployeeAggregateError):
            agg.cancel(emp_id, "hr", "Cannot")

    def test_can_close(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        assert aggregate_with_employee.can_close(emp_id) is False  # DRAFT
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        assert agg.can_close(emp_id) is True

    def test_close_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        agg = agg.close(emp_id, "hr", "Terminated")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.TERMINATED

    def test_close_not_allowed(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        with pytest.raises(EmployeeAggregateError):
            aggregate_with_employee.close(emp_id, "hr", "Cannot")

    def test_can_reopen(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        # Set to ACTIVE then resign
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        agg = agg.update_employee_status(emp_id, EmployeeStatus.RESIGNED, "hr", "resign")
        assert agg.can_reopen(emp_id) is True
        # Once terminated, also can reopen
        agg2 = agg.update_employee_status(emp_id, EmployeeStatus.TERMINATED, "hr", "term")
        assert agg2.can_reopen(emp_id) is True

    def test_reopen_success(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.update_employee_status(emp_id, EmployeeStatus.ACTIVE, "hr")
        agg = agg.update_employee_status(emp_id, EmployeeStatus.RESIGNED, "hr", "resign")
        agg = agg.reopen(emp_id, "hr", "Rehired")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.ACTIVE

    def test_reopen_not_allowed(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        with pytest.raises(EmployeeAggregateError):
            aggregate_with_employee.reopen(emp_id, "hr", "Cannot")

    def test_can_archive(self, empty_aggregate):
        assert empty_aggregate.can_archive() is True
        agg = empty_aggregate.add_employee(create_valid_employee(), "tester")
        assert agg.can_archive() is False

    def test_archive_success(self, empty_aggregate):
        agg = empty_aggregate.archive("admin", "No employees")
        assert agg.version == 2
        assert len(agg._audit_trail) == 2
        assert agg._audit_trail[-1]["action"] == "ARCHIVE"

    def test_archive_with_employees_raises(self, aggregate_with_employee):
        with pytest.raises(EmployeeAggregateError, match="Cannot archive aggregate with employees"):
            aggregate_with_employee.archive("admin")

    def test_can_unarchive(self, empty_aggregate):
        assert empty_aggregate.can_unarchive() is True

    def test_unarchive_success(self, empty_aggregate):
        agg = empty_aggregate.unarchive("admin")
        assert agg.version == 2
        assert agg._audit_trail[-1]["action"] == "UNARCHIVE"

    def test_get_statistics(self, empty_aggregate):
        emp1 = create_valid_employee(status=EmployeeStatus.ACTIVE, basic_salary=Decimal("5000000"), employee_type=EmployeeType.FULL_TIME)
        emp2 = create_valid_employee(employee_number="EMP-002", status=EmployeeStatus.ACTIVE, basic_salary=Decimal("7000000"), employee_type=EmployeeType.FULL_TIME, email="x@y.com")
        emp3 = create_valid_employee(employee_number="EMP-003", status=EmployeeStatus.INACTIVE, basic_salary=Decimal("3000000"), employee_type=EmployeeType.PART_TIME, email="z@w.com", gender=Gender.FEMALE)
        agg = empty_aggregate.add_employee(emp1, "tester")
        agg = agg.add_employee(emp2, "tester")
        agg = agg.add_employee(emp3, "tester")
        stats = agg.get_statistics()
        assert stats["total_employees"] == 3
        assert stats["active_employees"] == 2
        assert stats["inactive_employees"] == 1
        assert stats["status_distribution"][EmployeeStatus.ACTIVE.value] == 2
        assert stats["type_distribution"][EmployeeType.FULL_TIME.value] == 2
        assert stats["gender_distribution"][Gender.FEMALE.value] == 1
        assert stats["total_monthly_salary_bill"] == "12000000"
        assert stats["average_monthly_salary"] == "6000000"

    def test_clone(self, aggregate_with_employee):
        agg_clone = aggregate_with_employee.clone()
        assert agg_clone.aggregate_id != aggregate_with_employee.aggregate_id
        assert agg_clone.legal_entity_id == aggregate_with_employee.legal_entity_id
        assert len(agg_clone.employees) == len(aggregate_with_employee.employees)
        assert agg_clone.version == 1
        assert agg_clone._audit_trail[-1]["action"] == "CLONE"

    def test_to_dict_from_dict_roundtrip(self, aggregate_with_employee):
        d = aggregate_with_employee.to_dict()
        reconstructed = EmployeeAggregate.from_dict(d)
        assert reconstructed.aggregate_id == aggregate_with_employee.aggregate_id
        assert reconstructed.legal_entity_id == aggregate_with_employee.legal_entity_id
        assert len(reconstructed.employees) == len(aggregate_with_employee.employees)
        assert reconstructed.version == aggregate_with_employee.version

    def test_validate(self, empty_aggregate):
        result = empty_aggregate.validate()
        assert result["is_valid"] is True
        # Add duplicate employees to cause validation error
        emp1 = create_valid_employee()
        emp2 = create_valid_employee(employee_number=emp1.employee_number, email="other@example.com")
        agg = empty_aggregate.add_employee(emp1, "tester")
        # This will raise DuplicateEmployeeNumberError, but we can test validate separately
        # by manually setting duplicate data
        agg.employees[emp2.employee_id] = emp2
        agg.employee_by_number[emp2.employee_number] = emp2.employee_id
        result = agg.validate()
        assert result["is_valid"] is False
        assert any("Duplicate employee number" in e for e in result["errors"])

    def test_audit_trail(self, empty_aggregate):
        agg = empty_aggregate
        agg = agg.add_employee(create_valid_employee(), "tester")
        agg = agg.update_employee_status(list(agg.employees.keys())[0], EmployeeStatus.ACTIVE, "hr")
        trail = agg.audit_trail(limit=5)
        assert len(trail) >= 3
        assert trail[-1]["action"] == "UPDATE"
        assert trail[-1]["details"]["new_status"] == "active"

    def test_touch(self, empty_aggregate):
        old_version = empty_aggregate.version
        old_updated = empty_aggregate.updated_at
        agg = empty_aggregate.touch("toucher")
        assert agg.version == old_version + 1
        assert agg.updated_at > old_updated
        assert agg._audit_trail[-1]["action"] == "TOUCH"

    def test_snapshot(self, empty_aggregate):
        snap = empty_aggregate.snapshot()
        assert snap["aggregate_id"] == str(empty_aggregate.aggregate_id)
        assert snap["employee_count"] == 0
        assert snap["version"] == empty_aggregate.version

    def test_get_version(self, empty_aggregate):
        assert empty_aggregate.get_version() == 1

    def test_create_method(self, empty_aggregate):
        # Already tested via create factory
        pass

    def test_update_method(self, empty_aggregate):
        agg = empty_aggregate.update("updater", legal_entity_id=uuid4())
        assert agg.version == 2
        assert agg._audit_trail[-1]["action"] == "UPDATE"

    def test_delete_method(self, empty_aggregate):
        agg = empty_aggregate.delete("deleter", "empty")
        assert agg.version == 2
        assert agg._audit_trail[-1]["action"] == "DELETE"

    def test_delete_with_employees_raises(self, aggregate_with_employee):
        with pytest.raises(EmployeeAggregateError):
            aggregate_with_employee.delete("deleter")

    def test_restore(self, empty_aggregate):
        agg = empty_aggregate.restore("restorer")
        assert agg.version == 2
        assert agg._audit_trail[-1]["action"] == "RESTORE"

    def test_activate_deactivate_lock_unlock(self, empty_aggregate):
        agg = empty_aggregate.activate("activator")
        assert agg.version == 2
        assert agg._audit_trail[-1]["action"] == "ACTIVATE"
        agg = agg.deactivate("deactivator", "testing")
        assert agg.version == 3
        assert agg._audit_trail[-1]["action"] == "DEACTIVATE"
        agg = agg.lock("locker", "audit")
        assert agg.version == 4
        assert agg._audit_trail[-1]["action"] == "LOCK"
        agg = agg.unlock("unlocker")
        assert agg.version == 5
        assert agg._audit_trail[-1]["action"] == "UNLOCK"

    def test_can_reverse_always_false(self, empty_aggregate):
        assert empty_aggregate.can_reverse(uuid4()) is False

    def test_reverse_raises(self, empty_aggregate):
        with pytest.raises(NotImplementedError):
            empty_aggregate.reverse(uuid4(), "user", "reason")

    def test_register_event_and_get_events(self, empty_aggregate):
        event = MagicMock(spec=EmployeeCreatedEvent)
        empty_aggregate.register_event(event)
        events = empty_aggregate.get_events()
        assert len(events) == 1
        assert events[0] == event

    def test_pull_events_clears(self, empty_aggregate):
        event = MagicMock(spec=EmployeeCreatedEvent)
        empty_aggregate.register_event(event)
        events = empty_aggregate.pull_events()
        assert len(events) == 1
        assert len(empty_aggregate._events) == 0

    def test_clear_events(self, empty_aggregate):
        event = MagicMock(spec=EmployeeCreatedEvent)
        empty_aggregate.register_event(event)
        empty_aggregate.clear_events()
        assert len(empty_aggregate._events) == 0

    def test_apply(self, empty_aggregate):
        event = MagicMock(spec=EmployeeCreatedEvent)
        empty_aggregate.apply(event)
        assert len(empty_aggregate._events) == 1
        assert empty_aggregate._events[0] == event

    def test_from_events(self):
        agg_id = uuid4()
        legal_entity_id = uuid4()
        event1 = EmployeeCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            employee=create_valid_employee(),
            created_by="tester",
        )
        event2 = EmployeeResignedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            employee_id=uuid4(),
            employee_number="EMP-001",
            full_name="John Doe",
            resign_date=date.today(),
            reason="resign",
        )
        agg = EmployeeAggregate.from_events([event1, event2])
        assert agg.aggregate_id == agg_id
        assert agg.legal_entity_id == legal_entity_id  # from first event
        assert agg.version == 2  # number of events

    def test_from_events_empty_raises(self):
        with pytest.raises(ValueError, match="No events provided"):
            EmployeeAggregate.from_events([])

    def test_add_child_alias(self, empty_aggregate):
        emp = create_valid_employee()
        agg = empty_aggregate.add_child(emp, "tester")
        assert len(agg.employees) == 1

    def test_remove_child_alias(self, aggregate_with_employee):
        emp_id = list(aggregate_with_employee.employees.values())[0].employee_id
        agg = aggregate_with_employee.remove_child(emp_id, "admin")
        updated = agg.get_employee(emp_id)
        assert updated.status == EmployeeStatus.INACTIVE


# =============================================================================
# EmployeeAggregateRepository tests
# =============================================================================

@pytest.mark.asyncio
class TestEmployeeAggregateRepository:
    async def test_save_and_get_by_id(self):
        agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg)
        retrieved = await EmployeeAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved == agg

    async def test_get_by_legal_entity(self):
        legal_entity_id = uuid4()
        agg1 = EmployeeAggregate.create(legal_entity_id=legal_entity_id, created_by="tester")
        agg2 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg1)
        await EmployeeAggregateRepository.save(agg2)
        retrieved = await EmployeeAggregateRepository.get_by_legal_entity(legal_entity_id)
        assert retrieved == agg1

    async def test_get_all(self):
        await EmployeeAggregateRepository.clear()
        agg1 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        agg2 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg1)
        await EmployeeAggregateRepository.save(agg2)
        all_aggs = await EmployeeAggregateRepository.get_all()
        assert len(all_aggs) == 2
        assert agg1 in all_aggs
        assert agg2 in all_aggs

    async def test_update(self):
        agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg)
        agg = agg.touch("updater")
        await EmployeeAggregateRepository.update(agg)
        retrieved = await EmployeeAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved.version == 2

    async def test_delete(self):
        agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg)
        await EmployeeAggregateRepository.delete(agg.aggregate_id)
        retrieved = await EmployeeAggregateRepository.get_by_id(agg.aggregate_id)
        assert retrieved is None

    async def test_exists(self):
        agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg)
        exists = await EmployeeAggregateRepository.exists(agg.aggregate_id)
        assert exists is True
        exists_false = await EmployeeAggregateRepository.exists(uuid4())
        assert exists_false is False

    async def test_count(self):
        await EmployeeAggregateRepository.clear()
        agg1 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        agg2 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg1)
        await EmployeeAggregateRepository.save(agg2)
        count = await EmployeeAggregateRepository.count()
        assert count == 2

    async def test_list(self):
        await EmployeeAggregateRepository.clear()
        for _ in range(5):
            agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
            await EmployeeAggregateRepository.save(agg)
        results = await EmployeeAggregateRepository.list(limit=2, offset=1)
        assert len(results) == 2

    async def test_paginate(self):
        await EmployeeAggregateRepository.clear()
        for _ in range(5):
            agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
            await EmployeeAggregateRepository.save(agg)
        items, total = await EmployeeAggregateRepository.paginate(page=2, per_page=2)
        assert len(items) == 2
        assert total == 5

    async def test_search(self):
        await EmployeeAggregateRepository.clear()
        agg1 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        agg2 = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        # Add employee so search can find by employee data if fields include employee fields
        emp = create_valid_employee(full_name="John Search")
        agg1 = agg1.add_employee(emp, "tester")
        await EmployeeAggregateRepository.save(agg1)
        await EmployeeAggregateRepository.save(agg2)
        # Search by aggregate_id (default)
        results = await EmployeeAggregateRepository.search(str(agg1.aggregate_id))
        assert len(results) == 1
        assert results[0].aggregate_id == agg1.aggregate_id

    async def test_lock_unlock(self):
        agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg)
        locked = await EmployeeAggregateRepository.lock(agg.aggregate_id, "admin", "audit")
        assert locked.version == 2
        assert locked._audit_trail[-1]["action"] == "LOCK"
        unlocked = await EmployeeAggregateRepository.unlock(agg.aggregate_id, "admin")
        assert unlocked.version == 3
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    async def test_lock_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            await EmployeeAggregateRepository.lock(uuid4(), "admin", "reason")

    async def test_unlock_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            await EmployeeAggregateRepository.unlock(uuid4(), "admin")

    async def test_clear(self):
        await EmployeeAggregateRepository.clear()
        agg = EmployeeAggregate.create(legal_entity_id=uuid4(), created_by="tester")
        await EmployeeAggregateRepository.save(agg)
        assert await EmployeeAggregateRepository.count() == 1
        await EmployeeAggregateRepository.clear()
        assert await EmployeeAggregateRepository.count() == 0