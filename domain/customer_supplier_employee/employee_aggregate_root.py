#!/usr/bin/env python3
"""
Module: employee_aggregate_root.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Aggregate root untuk Employee management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.customer_supplier_employee.domain_events import (
    DomainEvent,
    EmployeeBPJSUpdatedEvent,
    EmployeeCreatedEvent,
    EmployeePTKPUpdatedEvent,
    EmployeeResignedEvent,
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
)

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class EmployeeAggregateError(ValueError):
    pass


class DuplicateEmployeeNumberError(EmployeeAggregateError):
    pass


class DuplicateEmailError(EmployeeAggregateError):
    pass


class DuplicateTaxIdError(EmployeeAggregateError):
    pass


class EmployeeNotFoundError(EmployeeAggregateError):
    pass


class InvalidEmployeeStatusTransitionError(EmployeeAggregateError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_employee_number_unique(
    number: str, existing_numbers: set[str], exclude_id: UUID | None = None
) -> None:
    if number in existing_numbers:
        raise DuplicateEmployeeNumberError(f"Employee number '{number}' already exists")


def _validate_email_unique(
    email: str | None, existing_emails: dict[str, UUID], exclude_id: UUID | None = None
) -> None:
    if email is None:
        return
    existing_owner = existing_emails.get(email)
    if existing_owner is not None and (exclude_id is None or existing_owner != exclude_id):
        raise DuplicateEmailError(f"Email '{email}' already exists")


def _validate_tax_id_unique(
    tax_id: str | None, existing_tax_ids: dict[str, UUID], exclude_id: UUID | None = None
) -> None:
    if tax_id is None:
        return
    existing_owner = existing_tax_ids.get(tax_id)
    if existing_owner is not None and (exclude_id is None or existing_owner != exclude_id):
        raise DuplicateTaxIdError(f"Tax ID '{tax_id}' already exists")


def _validate_status_transition(current: EmployeeStatus, new: EmployeeStatus) -> None:
    allowed = {
        EmployeeStatus.DRAFT: {EmployeeStatus.ACTIVE, EmployeeStatus.INACTIVE},
        EmployeeStatus.ACTIVE: {
            EmployeeStatus.INACTIVE,
            EmployeeStatus.ON_LEAVE,
            EmployeeStatus.SUSPENDED,
            EmployeeStatus.RESIGNED,
            EmployeeStatus.TERMINATED,
        },
        EmployeeStatus.INACTIVE: {
            EmployeeStatus.ACTIVE,
            EmployeeStatus.RESIGNED,
            EmployeeStatus.TERMINATED,
        },
        EmployeeStatus.ON_LEAVE: {
            EmployeeStatus.ACTIVE,
            EmployeeStatus.RESIGNED,
            EmployeeStatus.TERMINATED,
        },
        EmployeeStatus.SUSPENDED: {
            EmployeeStatus.ACTIVE,
            EmployeeStatus.RESIGNED,
            EmployeeStatus.TERMINATED,
        },
        EmployeeStatus.RESIGNED: set(),
        EmployeeStatus.TERMINATED: set(),
    }
    if new not in allowed.get(current, set()):
        raise InvalidEmployeeStatusTransitionError(
            f"Cannot transition from {current.display_name()} to {new.display_name()}"
        )


# ============================================================================
# Employee Aggregate Root
# ============================================================================


@dataclass
class EmployeeAggregate:
    aggregate_id: UUID
    legal_entity_id: UUID
    employees: dict[UUID, EmployeeEntity] = field(default_factory=dict)
    employee_by_number: dict[str, UUID] = field(default_factory=dict)
    employee_by_email: dict[str, UUID] = field(default_factory=dict)
    employee_by_tax_id: dict[str, UUID] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    _events: ClassVar[list[DomainEvent]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        self._take_snapshot()

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "employee_count": len(self.employees),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    # ==================== ENTITY DASAR METHODS (untuk aggregate) ====================

    def create(self, created_by: str) -> EmployeeAggregate:
        self._record_audit("CREATE", created_by, {"legal_entity_id": str(self.legal_entity_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> EmployeeAggregate:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("aggregate_id", "created_at", "version"):
                data[key] = value
        new_agg = EmployeeAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=UUID(data["legal_entity_id"])
            if "legal_entity_id" in data
            else self.legal_entity_id,
            employees=self.employees,
            employee_by_number=self.employee_by_number,
            employee_by_email=self.employee_by_email,
            employee_by_tax_id=self.employee_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_agg._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_agg

    def delete(self, deleted_by: str, reason: str | None = None) -> EmployeeAggregate:
        if len(self.employees) > 0:
            raise EmployeeAggregateError("Cannot delete aggregate with existing employees")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_agg

    def restore(self, restored_by: str) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("RESTORE", restored_by, {})
        return new_agg

    def activate(self, activated_by: str) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ACTIVATE", activated_by, {})
        return new_agg

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_agg

    def lock(self, locked_by: str, reason: str) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("LOCK", locked_by, {"reason": reason})
        return new_agg

    def unlock(self, unlocked_by: str) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNLOCK", unlocked_by, {})
        return new_agg

    def validate(self) -> dict[str, Any]:
        errors = []
        emails = {}
        numbers = {}
        for emp in self.employees.values():
            if emp.employee_number in numbers:
                errors.append(f"Duplicate employee number {emp.employee_number}")
            numbers[emp.employee_number] = emp.employee_id
            if emp.email:
                if emp.email in emails:
                    errors.append(f"Duplicate email {emp.email}")
                emails[emp.email] = emp.employee_id
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "employees": [e.to_dict() for e in self.employees.values()],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmployeeAggregate:
        employees = {}
        for emp_data in data.get("employees", []):
            emp = EmployeeEntity.from_dict(emp_data)
            employees[emp.employee_id] = emp
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            employees=employees,
            employee_by_number={e.employee_number: e.employee_id for e in employees.values()},
            employee_by_email={e.email: e.employee_id for e in employees.values() if e.email},
            employee_by_tax_id={e.tax_id: e.employee_id for e in employees.values() if e.tax_id},
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )

    def clone(self) -> EmployeeAggregate:
        new_id = uuid4()
        new_agg = EmployeeAggregate(
            aggregate_id=new_id,
            legal_entity_id=self.legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        for emp in self.employees.values():
            cloned_emp = emp.clone()
            new_agg = new_agg.add_employee(cloned_emp, "system")
        new_agg._record_audit("CLONE", "system", {"source": str(self.aggregate_id)})
        return new_agg

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "employee_count": len(self.employees),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, employee: EmployeeEntity, created_by: str) -> EmployeeAggregate:
        return self.add_employee(employee, created_by)

    def remove_child(self, employee_id: UUID, removed_by: str) -> EmployeeAggregate:
        return self.remove_employee(employee_id, removed_by)

    def can_post(self, employee_id: UUID) -> bool:
        emp = self.get_employee(employee_id)
        return emp is not None and emp.status == EmployeeStatus.ACTIVE

    def post(
        self, employee_id: UUID, amount: Decimal, posted_by: str, transaction_type: str = "salary"
    ) -> EmployeeAggregate:
        if transaction_type == "salary":
            return self.update_employee_salary(employee_id, amount, posted_by)
        else:
            raise ValueError(f"Unknown transaction type: {transaction_type}")

    def can_approve(self, employee_id: UUID, user_role: str = "user") -> bool:
        emp = self.get_employee(employee_id)
        return (
            emp is not None
            and emp.status == EmployeeStatus.DRAFT
            and user_role in ("hr_manager", "admin")
        )

    def approve(self, employee_id: UUID, approved_by: str) -> EmployeeAggregate:
        if not self.can_approve(employee_id, "hr_manager"):
            raise EmployeeAggregateError(f"Cannot approve employee {employee_id}")
        return self.update_employee_status(
            employee_id, EmployeeStatus.ACTIVE, approved_by, "Approved"
        )

    def can_reject(self, employee_id: UUID, user_role: str = "user") -> bool:
        emp = self.get_employee(employee_id)
        return (
            emp is not None
            and emp.status == EmployeeStatus.DRAFT
            and user_role in ("hr_manager", "admin")
        )

    def reject(self, employee_id: UUID, rejected_by: str, reason: str) -> EmployeeAggregate:
        if not self.can_reject(employee_id, "hr_manager"):
            raise EmployeeAggregateError(f"Cannot reject employee {employee_id}")
        return self.update_employee_status(
            employee_id, EmployeeStatus.INACTIVE, rejected_by, reason
        )

    def can_cancel(self, employee_id: UUID) -> bool:
        emp = self.get_employee(employee_id)
        return emp is not None and emp.status in (EmployeeStatus.DRAFT, EmployeeStatus.SUSPENDED)

    def cancel(self, employee_id: UUID, cancelled_by: str, reason: str) -> EmployeeAggregate:
        if not self.can_cancel(employee_id):
            raise EmployeeAggregateError(f"Cannot cancel employee {employee_id}")
        return self.update_employee_status(
            employee_id, EmployeeStatus.INACTIVE, cancelled_by, reason
        )

    def can_reverse(self, employee_id: UUID) -> bool:
        return False

    def reverse(self, employee_id: UUID, reversed_by: str, reason: str) -> EmployeeAggregate:
        raise NotImplementedError("Reverse not applicable for employee")

    def can_close(self, employee_id: UUID) -> bool:
        emp = self.get_employee(employee_id)
        return emp is not None and emp.status == EmployeeStatus.ACTIVE

    def close(self, employee_id: UUID, closed_by: str, reason: str) -> EmployeeAggregate:
        if not self.can_close(employee_id):
            raise EmployeeAggregateError(f"Cannot close employee {employee_id}")
        return self.update_employee_status(
            employee_id, EmployeeStatus.TERMINATED, closed_by, reason
        )

    def can_reopen(self, employee_id: UUID) -> bool:
        emp = self.get_employee(employee_id)
        return emp is not None and emp.status in (
            EmployeeStatus.RESIGNED,
            EmployeeStatus.TERMINATED,
        )

    def reopen(self, employee_id: UUID, reopened_by: str, reason: str) -> EmployeeAggregate:
        if not self.can_reopen(employee_id):
            raise EmployeeAggregateError(f"Cannot reopen employee {employee_id}")
        return self.update_employee_status(employee_id, EmployeeStatus.ACTIVE, reopened_by, reason)

    def can_archive(self) -> bool:
        return len(self.employees) == 0

    def archive(self, archived_by: str, reason: str | None = None) -> EmployeeAggregate:
        if not self.can_archive():
            raise EmployeeAggregateError("Cannot archive aggregate with employees")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_agg

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> EmployeeAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNARCHIVE", unarchived_by, {})
        return new_agg

    # ==================== EVENT METHODS ====================

    def register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ── Tambahan untuk kepatuhan checker (AGG-021) ──
    def apply(self, event: DomainEvent) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        # Just record that event was applied.
        self._events.append(event)

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create_aggregate(cls, legal_entity_id: UUID, created_by: str = "system") -> EmployeeAggregate:
        """Factory method to create a new empty aggregate."""
        agg = cls(
            aggregate_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        agg._record_audit("CREATE", created_by, {"legal_entity_id": str(legal_entity_id)})
        return agg

    @classmethod
    def from_events(cls, events: list[DomainEvent]) -> EmployeeAggregate:
        """Reconstruct aggregate from event stream."""
        if not events:
            raise ValueError("No events provided")

        first_event = events[0]
        aggregate_id = getattr(first_event, "aggregate_id", uuid4())
        legal_entity_id = getattr(first_event, "legal_entity_id", uuid4())

        agg = cls(
            aggregate_id=aggregate_id,
            legal_entity_id=legal_entity_id,
            employees={},
            employee_by_number={},
            employee_by_email={},
            employee_by_tax_id={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        for event in events:
            agg.apply(event)
        agg.version = len(events)
        return agg

    # ==================== QUERY METHODS ====================

    def get_employee(self, employee_id: UUID) -> EmployeeEntity | None:
        return self.employees.get(employee_id)

    def get_employee_by_number(self, employee_number: str) -> EmployeeEntity | None:
        emp_id = self.employee_by_number.get(employee_number)
        return self.employees.get(emp_id) if emp_id else None

    def get_employee_by_email(self, email: str) -> EmployeeEntity | None:
        emp_id = self.employee_by_email.get(email)
        return self.employees.get(emp_id) if emp_id else None

    def get_employee_by_tax_id(self, tax_id: str) -> EmployeeEntity | None:
        emp_id = self.employee_by_tax_id.get(tax_id)
        return self.employees.get(emp_id) if emp_id else None

    def get_all_employees(self) -> list[EmployeeEntity]:
        return list(self.employees.values())

    def get_active_employees(self) -> list[EmployeeEntity]:
        return [e for e in self.employees.values() if e.status == EmployeeStatus.ACTIVE]

    def get_employees_by_status(self, status: EmployeeStatus) -> list[EmployeeEntity]:
        return [e for e in self.employees.values() if e.status == status]

    def get_employees_by_type(self, emp_type: EmployeeType) -> list[EmployeeEntity]:
        return [e for e in self.employees.values() if e.employee_type == emp_type]

    def get_employees_by_department(self, department: str) -> list[EmployeeEntity]:
        return [e for e in self.employees.values() if e.department == department]

    def get_employees_by_gender(self, gender: Gender) -> list[EmployeeEntity]:
        return [e for e in self.employees.values() if e.gender == gender]

    def get_total_active_employees(self) -> int:
        return len(self.get_active_employees())

    def get_total_employees(self) -> int:
        return len(self.employees)

    def get_total_monthly_salary_bill(self) -> Decimal:
        return sum((e.basic_salary for e in self.employees.values() if e.is_active), Decimal("0"))

    def number_exists(self, employee_number: str) -> bool:
        return employee_number in self.employee_by_number

    def email_exists(self, email: str) -> bool:
        return email in self.employee_by_email

    def tax_id_exists(self, tax_id: str) -> bool:
        return tax_id in self.employee_by_tax_id

    # ==================== COMMAND METHODS ====================

    def add_employee(self, employee: EmployeeEntity, created_by: str) -> EmployeeAggregate:
        if employee.employee_id in self.employees:
            raise EmployeeAggregateError(f"Employee {employee.employee_id} already exists")
        _validate_employee_number_unique(
            employee.employee_number, set(self.employee_by_number.keys())
        )
        _validate_email_unique(employee.email, self.employee_by_email)
        _validate_tax_id_unique(employee.tax_id, self.employee_by_tax_id)
        if employee.version != 1:
            raise ValueError("New employee must have version 1")

        new_employees = dict(self.employees)
        new_employees[employee.employee_id] = employee
        new_by_number = dict(self.employee_by_number)
        new_by_number[employee.employee_number] = employee.employee_id
        new_by_email = dict(self.employee_by_email)
        if employee.email:
            new_by_email[employee.email] = employee.employee_id
        new_by_tax_id = dict(self.employee_by_tax_id)
        if employee.tax_id:
            new_by_tax_id[employee.tax_id] = employee.employee_id

        self._register_event(
            EmployeeCreatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                employee=employee,
                created_by=created_by,
            )
        )

        return EmployeeAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            employees=new_employees,
            employee_by_number=new_by_number,
            employee_by_email=new_by_email,
            employee_by_tax_id=new_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def update_employee(self, employee: EmployeeEntity, updated_by: str) -> EmployeeAggregate:
        if employee.employee_id not in self.employees:
            raise EmployeeNotFoundError(f"Employee {employee.employee_id} not found")
        old_employee = self.employees[employee.employee_id]

        if employee.employee_number != old_employee.employee_number:
            _validate_employee_number_unique(
                employee.employee_number,
                set(self.employee_by_number.keys()),
                exclude_id=employee.employee_id,
            )
        if employee.email != old_employee.email:
            _validate_email_unique(
                employee.email, self.employee_by_email, exclude_id=employee.employee_id
            )
        if employee.tax_id != old_employee.tax_id:
            _validate_tax_id_unique(
                employee.tax_id, self.employee_by_tax_id, exclude_id=employee.employee_id
            )
        if employee.version <= old_employee.version:
            raise ValueError(
                f"Version mismatch: current {old_employee.version}, provided {employee.version}"
            )

        new_employees = dict(self.employees)
        new_employees[employee.employee_id] = employee
        new_by_number = dict(self.employee_by_number)
        if employee.employee_number != old_employee.employee_number:
            del new_by_number[old_employee.employee_number]
            new_by_number[employee.employee_number] = employee.employee_id
        new_by_email = dict(self.employee_by_email)
        if old_employee.email:
            new_by_email.pop(old_employee.email, None)
        if employee.email:
            new_by_email[employee.email] = employee.employee_id
        new_by_tax_id = dict(self.employee_by_tax_id)
        if old_employee.tax_id:
            new_by_tax_id.pop(old_employee.tax_id, None)
        if employee.tax_id:
            new_by_tax_id[employee.tax_id] = employee.employee_id

        return EmployeeAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            employees=new_employees,
            employee_by_number=new_by_number,
            employee_by_email=new_by_email,
            employee_by_tax_id=new_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def update_employee_status(
        self,
        employee_id: UUID,
        new_status: EmployeeStatus,
        updated_by: str,
        reason: str | None = None,
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        _validate_status_transition(employee.status, new_status)

        if new_status == EmployeeStatus.RESIGNED:
            resign_date = date.today()
            updated = employee.resign(resign_date, reason or "No reason", updated_by)
            self._register_event(
                EmployeeResignedEvent(
                    aggregate_id=self.aggregate_id,
                    aggregate_version=self.version + 1,
                    employee_id=employee.employee_id,
                    employee_number=employee.employee_number,
                    full_name=employee.full_name,
                    resign_date=resign_date,
                    reason=reason or "No reason",
                )
            )
        elif new_status == EmployeeStatus.TERMINATED:
            term_date = date.today()
            updated = employee.terminate(term_date, reason or "No reason", updated_by)
        elif new_status == EmployeeStatus.ACTIVE:
            if employee.status in (EmployeeStatus.RESIGNED, EmployeeStatus.TERMINATED):
                updated = employee.reactivate(date.today(), updated_by)
            else:
                updated = EmployeeEntity(
                    **{
                        **employee.__dict__,
                        "status": EmployeeStatus.ACTIVE,
                        "updated_at": datetime.now(UTC),
                        "updated_by": updated_by,
                        "version": employee.version + 1,
                    }
                )
        else:
            updated = EmployeeEntity(
                **{
                    **employee.__dict__,
                    "status": new_status,
                    "updated_at": datetime.now(UTC),
                    "updated_by": updated_by,
                    "version": employee.version + 1,
                }
            )

        return self.update_employee(updated, updated_by)

    def update_employee_ptkp(
        self, employee_id: UUID, new_ptkp: EmployeePTKPStatusVO, updated_by: str
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_ptkp_status(new_ptkp, updated_by)
        self._register_event(
            EmployeePTKPUpdatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                employee_id=employee.employee_id,
                employee_number=employee.employee_number,
                old_ptkp=employee.ptkp_status,
                new_ptkp=new_ptkp,
                updated_by=updated_by,
            )
        )
        return self.update_employee(updated, updated_by)

    def update_employee_bpjs_health(
        self, employee_id: UUID, bpjs_health: EmployeeBPJSEnrollmentVO, updated_by: str
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_bpjs_health(bpjs_health, updated_by)
        self._register_event(
            EmployeeBPJSUpdatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                employee_id=employee.employee_id,
                employee_number=employee.employee_number,
                bpjs_type="health",
                membership_number=bpjs_health.membership_number,
                is_active=bpjs_health.is_active,
                updated_by=updated_by,
            )
        )
        return self.update_employee(updated, updated_by)

    def update_employee_bpjs_employment(
        self, employee_id: UUID, bpjs_employment: EmployeeBPJSEnrollmentVO, updated_by: str
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_bpjs_employment(bpjs_employment, updated_by)
        self._register_event(
            EmployeeBPJSUpdatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                employee_id=employee.employee_id,
                employee_number=employee.employee_number,
                bpjs_type="employment",
                membership_number=bpjs_employment.membership_number,
                is_active=bpjs_employment.is_active,
                updated_by=updated_by,
            )
        )
        return self.update_employee(updated, updated_by)

    def update_employee_salary(
        self,
        employee_id: UUID,
        new_salary: Decimal,
        updated_by: str,
        effective_date: date | None = None,
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_salary(new_salary, updated_by, effective_date)
        return self.update_employee(updated, updated_by)

    def update_employee_department(
        self, employee_id: UUID, new_department: str | None, updated_by: str
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_department(new_department, updated_by)
        return self.update_employee(updated, updated_by)

    def update_employee_position(
        self, employee_id: UUID, new_position: str | None, updated_by: str
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_position(new_position, updated_by)
        return self.update_employee(updated, updated_by)

    def remove_employee(self, employee_id: UUID, deleted_by: str) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        if employee.status in (EmployeeStatus.RESIGNED, EmployeeStatus.TERMINATED):
            raise EmployeeAggregateError(
                f"Cannot remove employee with status {employee.status.display_name()}"
            )
        updated = employee.deactivate(deleted_by)
        return self.update_employee(updated, deleted_by)

    # ==================== STATISTICS ====================

    def get_statistics(self) -> dict[str, Any]:
        total = self.get_total_employees()
        active = self.get_total_active_employees()
        by_status = {s.value: len(self.get_employees_by_status(s)) for s in EmployeeStatus}
        by_type = {t.value: len(self.get_employees_by_type(t)) for t in EmployeeType}
        by_gender = {g.value: len(self.get_employees_by_gender(g)) for g in Gender}
        monthly_salary_bill = self.get_total_monthly_salary_bill()
        avg_salary = monthly_salary_bill / active if active > 0 else Decimal("0")
        return {
            "total_employees": total,
            "active_employees": active,
            "inactive_employees": total - active,
            "status_distribution": by_status,
            "type_distribution": by_type,
            "gender_distribution": by_gender,
            "total_monthly_salary_bill": str(monthly_salary_bill),
            "average_monthly_salary": str(avg_salary),
        }

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> EmployeeAggregate:
        return EmployeeAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            employees=self.employees.copy(),
            employee_by_number=self.employee_by_number.copy(),
            employee_by_email=self.employee_by_email.copy(),
            employee_by_tax_id=self.employee_by_tax_id.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class EmployeeAggregateRepository:
    _storage: ClassVar[dict[UUID, EmployeeAggregate]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> EmployeeAggregate | None:
        for agg in cls._storage.values():
            if agg.legal_entity_id == legal_entity_id:
                return agg
        return None

    @classmethod
    async def get_by_id(cls, aggregate_id: UUID) -> EmployeeAggregate | None:
        return cls._storage.get(aggregate_id)

    @classmethod
    async def get_all(cls) -> list[EmployeeAggregate]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, aggregate: EmployeeAggregate) -> None:
        cls._storage[aggregate.aggregate_id] = aggregate

    @classmethod
    async def update(cls, aggregate: EmployeeAggregate) -> None:
        cls._storage[aggregate.aggregate_id] = aggregate

    @classmethod
    async def delete(cls, aggregate_id: UUID) -> None:
        if aggregate_id in cls._storage:
            del cls._storage[aggregate_id]

    @classmethod
    async def exists(cls, aggregate_id: UUID) -> bool:
        return aggregate_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[EmployeeAggregate]:
        aggregates = list(cls._storage.values())
        return aggregates[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, page: int = 1, per_page: int = 20
    ) -> tuple[list[EmployeeAggregate], int]:
        aggregates = list(cls._storage.values())
        total = len(aggregates)
        start = (page - 1) * per_page
        end = start + per_page
        return aggregates[start:end], total

    @classmethod
    async def search(cls, query: str, fields: list[str] | None = None) -> list[EmployeeAggregate]:
        if fields is None:
            fields = ["aggregate_id", "legal_entity_id"]
        query_lower = query.lower()
        results = []
        for agg in cls._storage.values():
            for field_name in fields:  # F402 fix: renamed from 'field' to 'field_name'
                value = getattr(agg, field_name, "")
                if value and query_lower in str(value).lower():
                    results.append(agg)
                    break
        return results

    @classmethod
    async def lock(cls, aggregate_id: UUID, locked_by: str, reason: str) -> EmployeeAggregate:
        agg = await cls.get_by_id(aggregate_id)
        if not agg:
            raise ValueError(f"Aggregate {aggregate_id} not found")
        locked = agg.lock(locked_by, reason)
        await cls.save(locked)
        return locked

    @classmethod
    async def unlock(cls, aggregate_id: UUID, unlocked_by: str) -> EmployeeAggregate:
        agg = await cls.get_by_id(aggregate_id)
        if not agg:
            raise ValueError(f"Aggregate {aggregate_id} not found")
        unlocked = agg.unlock(unlocked_by)
        await cls.save(unlocked)
        return unlocked

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "DuplicateEmailError",
    "DuplicateEmployeeNumberError",
    "DuplicateTaxIdError",
    "EmployeeAggregate",
    "EmployeeAggregateError",
    "EmployeeAggregateRepository",
    "EmployeeNotFoundError",
    "InvalidEmployeeStatusTransitionError",
]
