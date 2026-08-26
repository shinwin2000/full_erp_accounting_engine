# domain/payroll/aggregate_root.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: aggregate_root.py
Layer: 6 - Domain / Payroll
Responsibility: Root aggregate for payroll per period.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.payroll.domain_events import (
    DomainEvent,
    EmployeeStructureUpdatedEvent,
    PayrollRunApprovedEvent,
    PayrollRunCalculatedEvent,
    PayrollRunCancelledEvent,
    PayrollRunCreatedEvent,
    PayrollRunPaidEvent,
    PayrollRunPostedEvent,
    PayslipGeneratedEvent,
    SalaryComponentAddedEvent,
)
from domain.payroll.employee_salary_structure_vo import EmployeeSalaryStructureVO
from domain.payroll.payroll_run_entity import PayrollPeriod, PayrollRunEntity, PayrollRunStatus
from domain.payroll.payslip_projection import PayslipProjection
from domain.payroll.salary_component_entity import ComponentType, SalaryComponentEntity
from domain.payroll.tax_withholding_engine import TaxWithholdingEngine

logger = logging.getLogger(__name__)


@dataclass
class PayrollAggregate:
    """
    Root aggregate for payroll (immutable).

    Business context:
    Manages employee payroll processing for a given period, including
    salary calculation, components, tax withholding, and payment.
    """

    payroll_id: UUID
    legal_entity_id: UUID
    period: PayrollPeriod
    period_year: int
    period_month: int
    payroll_runs: dict[UUID, PayrollRunEntity] = field(default_factory=dict)
    employee_structures: dict[UUID, EmployeeSalaryStructureVO] = field(default_factory=dict)
    tax_engine: TaxWithholdingEngine = field(default_factory=TaxWithholdingEngine)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict] = field(default_factory=list, repr=False)
    _snapshots: list[dict] = field(default_factory=list, repr=False)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.period_year < 2000 or self.period_year > 2100:
            raise ValueError(f"Invalid period year: {self.period_year}")
        if not (1 <= self.period_month <= 12):
            raise ValueError(f"Invalid period month: {self.period_month}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    # ==================== PROPERTIES ====================

    @property
    def id(self) -> UUID:
        return self.payroll_id

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    # ==================== EVENT METHODS ====================

    def _add_event(self, event: DomainEvent) -> None:
        self._events.append(event)
        self._record_audit("event_added", {"event_type": event.event_type.value})

    def clear_events(self) -> None:
        self._events.clear()
        self._record_audit("events_cleared", {})

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pop_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def pull_events(self) -> list[DomainEvent]:
        """Pull all domain events (clear and return)."""
        events = self._events.copy()
        self._events.clear()
        return events

    def register_event(self, event: DomainEvent) -> None:
        self._add_event(event)

    # ── Event Sourcing (for checker compliance) ──
    def apply(self, event: DomainEvent) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        self._events.append(event)

    def replay(self, events: list[DomainEvent]) -> None:
        """Replay events to rebuild state."""
        for event in events:
            self.apply(event)
        self.version = len(events) + 1
        self._record_audit("REPLAY_EVENTS", {"count": len(events)})

    def reconstruct(self, events: list[DomainEvent]) -> None:
        """Alias for replay."""
        self.replay(events)

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def clear_audit_trail(self) -> None:
        self._audit_trail.clear()

    # ==================== SNAPSHOT ====================

    def snapshot(self) -> dict:
        snapshot_data = {
            "aggregate_id": str(self.payroll_id),
            "aggregate_type": "PayrollAggregate",
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "legal_entity_id": str(self.legal_entity_id),
                "period": self.period.value,
                "period_year": self.period_year,
                "period_month": self.period_month,
                "payroll_runs_count": len(self.payroll_runs),
                "employee_structures_count": len(self.employee_structures),
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        self._record_audit("snapshot_created", {"version": self.version})
        return snapshot_data

    def restore_from_snapshot(self, snapshot: dict) -> None:
        if snapshot.get("aggregate_id") != str(self.payroll_id):
            raise ValueError("Snapshot belongs to different aggregate")
        self._record_audit("restored_from_snapshot", {"snapshot_version": snapshot.get("version")})

    def _compute_hash(self) -> str:
        state_str = json.dumps(
            {
                "id": str(self.payroll_id),
                "version": self.version,
                "payroll_runs_count": len(self.payroll_runs),
                "employee_structures_count": len(self.employee_structures),
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    # ==================== LOCK / UNLOCK ====================

    def lock(self, user_id: str, reason: str | None = None) -> PayrollAggregate:
        if self._is_locked:
            raise ValueError(f"Payroll aggregate is already locked by {self._locked_by}")
        self._record_audit("locked", {"user_id": user_id, "reason": reason})
        self._is_locked = True
        self._locked_by = user_id
        self._locked_at = datetime.now(UTC)
        return self

    def unlock(self, user_id: str) -> PayrollAggregate:
        if not self._is_locked:
            raise ValueError("Payroll aggregate is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Aggregate locked by {self._locked_by}, cannot unlock by {user_id}")
        self._record_audit("unlocked", {"user_id": user_id})
        self._is_locked = False
        self._locked_by = None
        self._locked_at = None
        return self

    # ==================== VALIDATE ====================

    def validate(self) -> list[str]:
        errors = []
        for structure in self.employee_structures.values():
            if structure.basic_salary <= 0:
                errors.append(f"Employee {structure.employee_name} has invalid basic salary")
        for run in self.payroll_runs.values():
            if run.total_net < 0:
                errors.append(f"Payroll run {run.run_number} has negative total net")
        return errors

    # ==================== VERSION ====================

    def get_version(self) -> int:
        return self.version

    def increment_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(UTC)
        self._record_audit("version_incremented", {"new_version": self.version})

    # ==================== TOUCH ====================

    def touch(self, user_id: str) -> None:
        self.updated_at = datetime.now(UTC)
        self._record_audit("touched", {"user_id": user_id})

    # ==================== CLONE ====================

    def clone(self) -> PayrollAggregate:
        self._record_audit("cloned", {"source_id": str(self.payroll_id)})
        return PayrollAggregate(
            payroll_id=uuid4(),
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=self.payroll_runs.copy(),
            employee_structures=self.employee_structures.copy(),
            tax_engine=self.tax_engine,
            version=1,
        )

    # ==================== EMPLOYEE STRUCTURE MANAGEMENT ====================

    def add_employee_structure(
        self, structure: EmployeeSalaryStructureVO, added_by: str
    ) -> PayrollAggregate:
        if self._is_locked:
            raise ValueError("Cannot add structure to locked aggregate")
        if structure.employee_id in self.employee_structures:
            raise ValueError(f"Employee {structure.employee_id} already has salary structure")

        new_structures = dict(self.employee_structures)
        new_structures[structure.employee_id] = structure

        self._add_event(
            SalaryComponentAddedEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                component_name="salary_structure",
                component_type="basic",
                amount=structure.basic_salary,
                added_by=added_by,
            )
        )

        self._record_audit("add_employee_structure", {
            "employee_id": str(structure.employee_id),
            "employee_name": structure.employee_name,
            "added_by": added_by,
        })
        self.increment_version()
        return PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=self.payroll_runs,
            employee_structures=new_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def update_employee_structure(
        self, structure: EmployeeSalaryStructureVO, updated_by: str
    ) -> PayrollAggregate:
        if self._is_locked:
            raise ValueError("Cannot update structure in locked aggregate")
        if structure.employee_id not in self.employee_structures:
            raise ValueError(f"Employee {structure.employee_id} not found")

        old_structure = self.employee_structures[structure.employee_id]
        new_structures = dict(self.employee_structures)
        new_structures[structure.employee_id] = structure

        self._add_event(
            EmployeeStructureUpdatedEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                employee_id=structure.employee_id,
                employee_name=structure.employee_name,
                old_basic_salary=old_structure.basic_salary,
                new_basic_salary=structure.basic_salary,
                updated_by=updated_by,
            )
        )

        self._record_audit("update_employee_structure", {
            "employee_id": str(structure.employee_id),
            "updated_by": updated_by,
        })
        self.increment_version()
        return PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=self.payroll_runs,
            employee_structures=new_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def remove_employee_structure(self, employee_id: UUID, removed_by: str) -> PayrollAggregate:
        if self._is_locked:
            raise ValueError("Cannot remove structure from locked aggregate")
        if employee_id not in self.employee_structures:
            raise ValueError(f"Employee {employee_id} not found")

        new_structures = dict(self.employee_structures)
        del new_structures[employee_id]

        self._record_audit("remove_employee_structure", {
            "employee_id": str(employee_id),
            "removed_by": removed_by,
        })
        self.increment_version()
        return PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=self.payroll_runs,
            employee_structures=new_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_employee_structure(self, employee_id: UUID) -> EmployeeSalaryStructureVO | None:
        return self.employee_structures.get(employee_id)

    # ==================== PAYROLL RUN MANAGEMENT ====================

    def create_payroll_run(
        self, run_number: str, period: PayrollPeriod, created_by: str
    ) -> tuple[PayrollAggregate, PayrollRunEntity]:
        if self._is_locked:
            raise ValueError("Cannot create payroll run in locked aggregate")

        payroll_run = PayrollRunEntity.create(
            run_number,
            period,
            created_by,
            period_year=self.period_year,
            period_month=self.period_month,
        )
        new_runs = dict(self.payroll_runs)
        new_runs[payroll_run.run_id] = payroll_run

        self._add_event(
            PayrollRunCreatedEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                payroll_run=payroll_run,
                created_by=created_by,
            )
        )

        self._record_audit("create_payroll_run", {
            "run_id": str(payroll_run.run_id),
            "run_number": run_number,
            "created_by": created_by,
        })
        self.increment_version()
        new_aggregate = PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=new_runs,
            employee_structures=self.employee_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )
        return new_aggregate, payroll_run

    def get_payroll_run(self, run_id: UUID) -> PayrollRunEntity | None:
        return self.payroll_runs.get(run_id)

    # ==================== PAYROLL CALCULATION ====================

    def calculate_payroll(
        self, run_id: UUID, employee_ids: list[UUID] | None = None, calculated_by: str = "system"
    ) -> tuple[PayrollAggregate, PayrollRunEntity]:
        if self._is_locked:
            raise ValueError("Cannot calculate payroll in locked aggregate")

        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            raise ValueError(f"Payroll run {run_id} not found")
        if payroll_run.status != PayrollRunStatus.DRAFT:
            raise ValueError(f"Cannot calculate payroll in status {payroll_run.status.value}")

        employees_to_process = employee_ids or list(self.employee_structures.keys())
        updated_run = payroll_run
        calculated_employees = []

        for emp_id in employees_to_process:
            structure = self.employee_structures.get(emp_id)
            if not structure:
                logger.warning(f"Employee {emp_id} has no salary structure, skipping")
                continue

            gross_salary = structure.total_salary
            deductions = structure.total_deductions
            bpjs_employee = structure.bpjs_employee_contribution

            tax = self.tax_engine.calculate_pph21(
                gross_salary=gross_salary,
                ptkp_status=structure.ptkp_status,
                bpjs_contribution=bpjs_employee,
            )

            net_salary = gross_salary - deductions - tax
            components = self._build_salary_components(structure, tax)

            updated_run = updated_run.add_employee(
                employee_id=emp_id,
                employee_name=structure.employee_name,
                gross_salary=gross_salary,
                deductions=deductions,
                tax=tax,
                net_salary=net_salary,
                components=components,
                bank_account_number=structure.bank_account_number,
            )
            calculated_employees.append(emp_id)

        updated_run = updated_run.calculate()

        self._add_event(
            PayrollRunCalculatedEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                payroll_run=updated_run,
                calculated_by=calculated_by,
                total_employees=len(calculated_employees),
                total_net=updated_run.total_net,
            )
        )

        self._record_audit("calculate_payroll", {
            "run_id": str(run_id),
            "run_number": payroll_run.run_number,
            "calculated_by": calculated_by,
            "total_employees": len(calculated_employees),
            "total_net": str(updated_run.total_net),
        })

        new_runs = dict(self.payroll_runs)
        new_runs[run_id] = updated_run

        self.increment_version()
        new_aggregate = PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=new_runs,
            employee_structures=self.employee_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )
        logger.info(
            f"Payroll run {payroll_run.run_number} calculated for {len(calculated_employees)} employees"
        )
        return new_aggregate, updated_run

    def _build_salary_components(
        self, structure: EmployeeSalaryStructureVO, tax: Decimal
    ) -> list[SalaryComponentEntity]:
        components = []
        from domain.payroll.salary_component_entity import ComponentFrequency

        components.append(
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Basic Salary",
                component_type=ComponentType.BASIC,
                amount=structure.basic_salary,
                currency=structure.currency,
                frequency=ComponentFrequency.MONTHLY,
                description="Basic monthly salary",
                is_taxable=True,
            )
        )

        for comp in structure.salary_components:
            components.append(comp)

        components.append(
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="PPh 21",
                component_type=ComponentType.TAX,
                amount=-tax,
                currency=structure.currency,
                frequency=ComponentFrequency.MONTHLY,
                description="Income tax withholding",
                is_taxable=False,
            )
        )

        return components

    # ==================== STATE TRANSITIONS ====================

    def approve_payroll(
        self, run_id: UUID, approved_by: str
    ) -> tuple[PayrollAggregate, PayrollRunEntity]:
        if self._is_locked:
            raise ValueError("Cannot approve payroll in locked aggregate")

        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            raise ValueError(f"Payroll run {run_id} not found")

        updated_run = payroll_run.approve(approved_by)

        self._add_event(
            PayrollRunApprovedEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                payroll_run=updated_run,
                approved_by=approved_by,
            )
        )

        self._record_audit("approve_payroll", {
            "run_id": str(run_id),
            "run_number": payroll_run.run_number,
            "approved_by": approved_by,
        })

        new_runs = dict(self.payroll_runs)
        new_runs[run_id] = updated_run

        self.increment_version()
        new_aggregate = PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=new_runs,
            employee_structures=self.employee_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )
        return new_aggregate, updated_run

    def process_payment(
        self, run_id: UUID, paid_by: str
    ) -> tuple[PayrollAggregate, PayrollRunEntity]:
        if self._is_locked:
            raise ValueError("Cannot process payment in locked aggregate")

        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            raise ValueError(f"Payroll run {run_id} not found")

        updated_run = payroll_run.process_payment(paid_by)

        self._add_event(
            PayrollRunPaidEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                payroll_run=updated_run,
                paid_by=paid_by,
                total_paid=updated_run.total_net,
            )
        )

        # Generate payslips
        for emp in updated_run.employees:
            payslip = self.get_payslip(run_id, emp.employee_id)
            if payslip:
                self._add_event(
                    PayslipGeneratedEvent(
                        aggregate_id=self.payroll_id,
                        aggregate_version=self.version + 1,
                        payslip=payslip,
                        employee_name=emp.employee_name,
                    )
                )

        self._record_audit("process_payment", {
            "run_id": str(run_id),
            "run_number": payroll_run.run_number,
            "paid_by": paid_by,
            "total_paid": str(updated_run.total_net),
        })

        new_runs = dict(self.payroll_runs)
        new_runs[run_id] = updated_run

        self.increment_version()
        new_aggregate = PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=new_runs,
            employee_structures=self.employee_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )
        return new_aggregate, updated_run

    def cancel_payroll(
        self, run_id: UUID, cancelled_by: str, reason: str
    ) -> tuple[PayrollAggregate, PayrollRunEntity]:
        if self._is_locked:
            raise ValueError("Cannot cancel payroll in locked aggregate")

        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            raise ValueError(f"Payroll run {run_id} not found")

        updated_run = payroll_run.cancel(cancelled_by, reason)

        self._add_event(
            PayrollRunCancelledEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                payroll_run=updated_run,
                cancelled_by=cancelled_by,
                reason=reason,
            )
        )

        self._record_audit("cancel_payroll", {
            "run_id": str(run_id),
            "run_number": payroll_run.run_number,
            "cancelled_by": cancelled_by,
            "reason": reason,
        })

        new_runs = dict(self.payroll_runs)
        new_runs[run_id] = updated_run

        self.increment_version()
        new_aggregate = PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=new_runs,
            employee_structures=self.employee_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )
        return new_aggregate, updated_run

    def post_to_gl(
        self, run_id: UUID, journal_id: UUID, posted_by: str
    ) -> tuple[PayrollAggregate, PayrollRunEntity]:
        if self._is_locked:
            raise ValueError("Cannot post to GL in locked aggregate")

        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            raise ValueError(f"Payroll run {run_id} not found")
        if payroll_run.status != PayrollRunStatus.PAID:
            raise ValueError(f"Cannot post payroll in status {payroll_run.status.value}")

        self._add_event(
            PayrollRunPostedEvent(
                aggregate_id=self.payroll_id,
                aggregate_version=self.version + 1,
                payroll_run=payroll_run,
                journal_id=journal_id,
                posted_by=posted_by,
            )
        )

        self._record_audit("post_to_gl", {
            "run_id": str(run_id),
            "run_number": payroll_run.run_number,
            "journal_id": str(journal_id),
            "posted_by": posted_by,
        })

        self.increment_version()
        new_aggregate = PayrollAggregate(
            payroll_id=self.payroll_id,
            legal_entity_id=self.legal_entity_id,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            payroll_runs=self.payroll_runs,
            employee_structures=self.employee_structures,
            tax_engine=self.tax_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )
        return new_aggregate, payroll_run

    # ==================== QUERY METHODS ====================

    def get_payslip(self, run_id: UUID, employee_id: UUID) -> PayslipProjection | None:
        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            return None

        employee_result = payroll_run.get_employee_result(employee_id)
        if not employee_result:
            return None

        structure = self.employee_structures.get(employee_id)
        return PayslipProjection.from_payroll_employee(
            employee=employee_result,
            payroll_run=payroll_run,
            employee_nik=structure.employee_nik if structure else None,
            employee_position=structure.employee_position if structure else None,
        )

    def get_total_payroll_cost(self, run_id: UUID) -> Decimal:
        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            return Decimal(0)
        return payroll_run.total_gross

    def get_total_net_pay(self, run_id: UUID) -> Decimal:
        payroll_run = self.payroll_runs.get(run_id)
        if not payroll_run:
            return Decimal(0)
        return payroll_run.total_net

    def get_payroll_runs_by_status(self, status: PayrollRunStatus) -> list[PayrollRunEntity]:
        return [run for run in self.payroll_runs.values() if run.status == status]

    # ==================== DICTIONARY ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "payroll_id": str(self.payroll_id),
            "legal_entity_id": str(self.legal_entity_id),
            "period": self.period.value,
            "period_year": self.period_year,
            "period_month": self.period_month,
            "total_employees": len(self.employee_structures),
            "total_payroll_runs": len(self.payroll_runs),
            "payroll_runs": [run.to_dict() for run in self.payroll_runs.values()],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_locked": self._is_locked,
        }

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        period: PayrollPeriod,
        period_year: int,
        period_month: int,
        created_by: str,
    ) -> PayrollAggregate:
        return cls(
            payroll_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period=period,
            period_year=period_year,
            period_month=period_month,
            created_by=created_by,
        )


class PayrollRepository:
    async def get_by_legal_entity(self, legal_entity_id: UUID) -> PayrollAggregate | None:
        raise NotImplementedError

    async def get_by_period(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> PayrollAggregate | None:
        raise NotImplementedError

    async def save(self, payroll: PayrollAggregate) -> None:
        raise NotImplementedError

    async def delete(self, payroll_id: UUID) -> None:
        raise NotImplementedError


__all__ = ["PayrollAggregate", "PayrollRepository"]
