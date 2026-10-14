#!/usr/bin/env python3
"""
Module: employee_aggregate_root.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Aggregate root untuk Employee management (domain murni).

PERBAIKAN (2026-10-13):
- _events, _audit_trail, _snapshots dari ClassVar -> instance field.
- EmployeeAggregateRepository (in-memory) DIHAPUS dari file ini.
  Implementasi nyata ada di adapter SQLAlchemy (SQLAlchemyEmployeeRepository).
- Immutable-style: setiap mutation mengembalikan instance baru.

Catatan: File ini HANYA berisi domain logic. Tidak ada repository
implementasi nyata di sini.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
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
    if existing_owner is not None and (
        exclude_id is None or existing_owner != exclude_id
    ):
        raise DuplicateEmailError(f"Email '{email}' already exists")


def _validate_tax_id_unique(
    tax_id: str | None,
    existing_tax_ids: dict[str, UUID],
    exclude_id: UUID | None = None,
) -> None:
    if tax_id is None:
        return
    existing_owner = existing_tax_ids.get(tax_id)
    if existing_owner is not None and (
        exclude_id is None or existing_owner != exclude_id
    ):
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
    # Instance-level (bukan ClassVar!)
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

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

    def _record_audit(
        self, action: str, performed_by: str, details: dict[str, Any]
    ) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "details": details,
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > 1000:
            self._audit_trail.pop(0)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

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

    def apply(self, event: DomainEvent) -> None:
        """Event sourcing placeholder."""
        self._events.append(event)

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
        return [
            e for e in self.employees.values() if e.status == EmployeeStatus.ACTIVE
        ]

    def get_employees_by_status(
        self, status: EmployeeStatus
    ) -> list[EmployeeEntity]:
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
        return sum(
            (
                e.basic_salary
                for e in self.employees.values()
                if e.is_active
            ),
            Decimal("0"),
        )

    def number_exists(self, employee_number: str) -> bool:
        return employee_number in self.employee_by_number

    def email_exists(self, email: str) -> bool:
        return email in self.employee_by_email

    def tax_id_exists(self, tax_id: str) -> bool:
        return tax_id in self.employee_by_tax_id

    # ==================== COMMAND METHODS ====================

    def add_employee(
        self, employee: EmployeeEntity, created_by: str
    ) -> EmployeeAggregate:
        if employee.employee_id in self.employees:
            raise EmployeeAggregateError(
                f"Employee {employee.employee_id} already exists"
            )
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
            EmployeeCreatedEvent.create(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                employee_id=employee.employee_id,
                employee_code=employee.employee_number,
                employee_name=employee.full_name,
                legal_entity_id=employee.legal_entity_id,
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
            _events=self._events.copy(),
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
        )

    def update_employee(
        self, employee: EmployeeEntity, updated_by: str
    ) -> EmployeeAggregate:
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
                employee.email,
                self.employee_by_email,
                exclude_id=employee.employee_id,
            )
        if employee.tax_id != old_employee.tax_id:
            _validate_tax_id_unique(
                employee.tax_id,
                self.employee_by_tax_id,
                exclude_id=employee.employee_id,
            )
        if employee.version <= old_employee.version:
            raise ValueError(
                f"Version mismatch: current {old_employee.version}, "
                f"provided {employee.version}"
            )

        new_employees = dict(self.employees)
        new_employees[employee.employee_id] = employee
        new_by_number = dict(self.employee_by_number)
        if employee.employee_number != old_employee.employee_number:
            new_by_number.pop(old_employee.employee_number, None)
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
            _events=self._events.copy(),
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
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
                EmployeeResignedEvent.create(
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
            if employee.status in (
                EmployeeStatus.RESIGNED,
                EmployeeStatus.TERMINATED,
            ):
                updated = employee.reactivate(date.today(), updated_by)
            else:
                # Tidak ada method .update() di EmployeeEntity, jadi kita
                # bikin instance baru pakai constructor langsung.
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
        self,
        employee_id: UUID,
        new_ptkp: EmployeePTKPStatusVO,
        updated_by: str,
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_ptkp_status(new_ptkp, updated_by)
        self._register_event(
            EmployeePTKPUpdatedEvent.create(
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
        self,
        employee_id: UUID,
        bpjs_health: EmployeeBPJSEnrollmentVO,
        updated_by: str,
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_bpjs_health(bpjs_health, updated_by)
        self._register_event(
            EmployeeBPJSUpdatedEvent.create(
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
        self,
        employee_id: UUID,
        bpjs_employment: EmployeeBPJSEnrollmentVO,
        updated_by: str,
    ) -> EmployeeAggregate:
        employee = self.get_employee(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        updated = employee.update_bpjs_employment(bpjs_employment, updated_by)
        self._register_event(
            EmployeeBPJSUpdatedEvent.create(
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
                f"Cannot remove employee with status "
                f"{employee.status.display_name()}"
            )
        updated_data = employee.to_dict()
        updated_data["status"] = EmployeeStatus.INACTIVE.value
        updated_data["updated_at"] = datetime.now(UTC).isoformat()
        updated_data["updated_by"] = deleted_by
        updated_data["version"] = employee.version + 1
        updated_employee = EmployeeEntity.from_dict(updated_data)
        return self.update_employee(updated_employee, deleted_by)

    # ==================== STATISTICS ====================

    def get_statistics(self) -> dict[str, Any]:
        total = self.get_total_employees()
        active = self.get_total_active_employees()
        by_status = {
            s.value: len(self.get_employees_by_status(s)) for s in EmployeeStatus
        }
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

    # ==================== SERIALIZATION ====================

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
        employees: dict[UUID, EmployeeEntity] = {}
        for emp_data in data.get("employees", []):
            emp = EmployeeEntity.from_dict(emp_data)
            employees[emp.employee_id] = emp
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            employees=employees,
            employee_by_number={
                e.employee_number: e.employee_id for e in employees.values()
            },
            employee_by_email={
                e.email: e.employee_id for e in employees.values() if e.email
            },
            employee_by_tax_id={
                e.tax_id: e.employee_id for e in employees.values() if e.tax_id
            },
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )

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
            _events=self._events.copy(),
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
        )

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create_aggregate(
        cls, legal_entity_id: UUID, created_by: str = "system"
    ) -> EmployeeAggregate:
        agg = cls(
            aggregate_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        agg._record_audit(
            "CREATE", created_by, {"legal_entity_id": str(legal_entity_id)}
        )
        return agg

    @classmethod
    def from_events(cls, events: list[DomainEvent]) -> EmployeeAggregate:
        if not events:
            raise ValueError("No events provided")
        first_event = events[0]
        aggregate_id = first_event.aggregate_id
        legal_entity_id_str = first_event.event_data.get("legal_entity_id")
        legal_entity_id = (
            UUID(legal_entity_id_str) if legal_entity_id_str else uuid4()
        )
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


__all__ = [
    "DuplicateEmailError",
    "DuplicateEmployeeNumberError",
    "DuplicateTaxIdError",
    "EmployeeAggregate",
    "EmployeeAggregateError",
    "EmployeeNotFoundError",
    "InvalidEmployeeStatusTransitionError",
]
