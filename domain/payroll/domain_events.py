#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Payroll
Responsibility: Event: PayrollRunCreated, PayrollRunApproved, etc.
               Mendefinisikan semua domain events yang dihasilkan oleh
               Payroll aggregate. Event ini digunakan untuk komunikasi
               antar bounded context, event sourcing, dan proyeksi read model.

Dependencies:
- standard library (uuid, datetime, dataclass, json)
- domain.payroll.payroll_run_entity (PayrollRunEntity, PayrollRunStatus)
- domain.payroll.payslip_projection (PayslipProjection)

Audit: Setiap event domain payroll dictat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.payroll.payroll_run_entity import PayrollRunEntity
from domain.payroll.payslip_projection import PayslipProjection

# === 1. DOMAIN EVENT BASE ===


class DomainEventType(Enum):
    """Tipe domain event untuk Payroll."""

    PAYROLL_RUN_CREATED = "payroll_run_created"
    PAYROLL_RUN_CALCULATED = "payroll_run_calculated"
    PAYROLL_RUN_APPROVED = "payroll_run_approved"
    PAYROLL_RUN_PAID = "payroll_run_paid"
    PAYROLL_RUN_POSTED = "payroll_run_posted"  # for GL posting
    PAYROLL_RUN_CANCELLED = "payroll_run_cancelled"
    PAYSLIP_GENERATED = "payslip_generated"
    PAYSLIP_SENT_TO_EMPLOYEE = "payslip_sent_to_employee"
    EMPLOYEE_STRUCTURE_UPDATED = "employee_structure_updated"
    SALARY_COMPONENT_ADDED = "salary_component_added"


@dataclass
class DomainEvent:
    """
    Base class untuk semua domain events Payroll.
    """

    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": str(self.event_id),
                "event_type": self.event_type.value,
                "aggregate_id": str(self.aggregate_id),
                "aggregate_version": self.aggregate_version,
                "occurred_at": self.occurred_at.isoformat(),
                "user_id": self.user_id,
                "correlation_id": self.correlation_id,
                "event_data": self.event_data,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        data = json.loads(json_str)
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
        )


# === 2. CONCRETE DOMAIN EVENTS ===


@dataclass
class PayrollRunCreatedEvent(DomainEvent):
    """Event ketika proses penggajian baru dibuat."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payroll_run: PayrollRunEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "run_id": str(payroll_run.run_id),
            "run_number": payroll_run.run_number,
            "period": payroll_run.period.value,
            "period_year": payroll_run.period_year,
            "period_month": payroll_run.period_month,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYROLL_RUN_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayrollRunCalculatedEvent(DomainEvent):
    """Event ketika penggajian selesai dihitung (processed)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payroll_run: PayrollRunEntity,
        calculated_by: str,
        total_employees: int,
        total_net: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "run_id": str(payroll_run.run_id),
            "run_number": payroll_run.run_number,
            "period": f"{payroll_run.period_month}/{payroll_run.period_year}",
            "calculated_by": calculated_by,
            "total_employees": total_employees,
            "total_net": str(total_net),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYROLL_RUN_CALCULATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayrollRunApprovedEvent(DomainEvent):
    """Event ketika penggajian disetujui."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payroll_run: PayrollRunEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "run_id": str(payroll_run.run_id),
            "run_number": payroll_run.run_number,
            "period": f"{payroll_run.period_month}/{payroll_run.period_year}",
            "approved_by": approved_by,
            "total_net": str(payroll_run.total_net),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYROLL_RUN_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayrollRunPaidEvent(DomainEvent):
    """Event ketika penggajian dibayarkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payroll_run: PayrollRunEntity,
        paid_by: str,
        total_paid: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "run_id": str(payroll_run.run_id),
            "run_number": payroll_run.run_number,
            "period": f"{payroll_run.period_month}/{payroll_run.period_year}",
            "paid_by": paid_by,
            "total_paid": str(total_paid),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYROLL_RUN_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayrollRunPostedEvent(DomainEvent):
    """Event ketika penggajian diposting ke General Ledger."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payroll_run: PayrollRunEntity,
        journal_id: UUID,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "run_id": str(payroll_run.run_id),
            "run_number": payroll_run.run_number,
            "period": f"{payroll_run.period_month}/{payroll_run.period_year}",
            "journal_id": str(journal_id),
            "posted_by": posted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYROLL_RUN_POSTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayrollRunCancelledEvent(DomainEvent):
    """Event ketika penggajian dibatalkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payroll_run: PayrollRunEntity,
        cancelled_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "run_id": str(payroll_run.run_id),
            "run_number": payroll_run.run_number,
            "period": f"{payroll_run.period_month}/{payroll_run.period_year}",
            "cancelled_by": cancelled_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYROLL_RUN_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayslipGeneratedEvent(DomainEvent):
    """Event ketika slip gaji dihasilkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payslip: PayslipProjection,
        employee_name: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "payslip_id": str(payslip.payslip_id),
            "employee_id": str(payslip.employee_id),
            "employee_name": employee_name,
            "period": f"{payslip.period_month}/{payslip.period_year}",
            "net_salary": str(payslip.net_salary),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYSLIP_GENERATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PayslipSentToEmployeeEvent(DomainEvent):
    """Event ketika slip gaji dikirim ke karyawan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payslip_id: UUID,
        employee_id: UUID,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "payslip_id": str(payslip_id),
            "employee_id": str(employee_id),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PAYSLIP_SENT_TO_EMPLOYEE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class EmployeeStructureUpdatedEvent(DomainEvent):
    """Event ketika struktur gaji karyawan diperbarui."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        employee_id: UUID,
        employee_name: str,
        old_basic_salary: Decimal,
        new_basic_salary: Decimal,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "employee_id": str(employee_id),
            "employee_name": employee_name,
            "old_basic_salary": str(old_basic_salary),
            "new_basic_salary": str(new_basic_salary),
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.EMPLOYEE_STRUCTURE_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SalaryComponentAddedEvent(DomainEvent):
    """Event ketika komponen gaji baru ditambahkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        component_name: str,
        component_type: str,
        amount: Decimal,
        added_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "component_name": component_name,
            "component_type": component_type,
            "amount": str(amount),
            "added_by": added_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SALARY_COMPONENT_ADDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# === 3. ALIASES FOR SERVICE LAYER COMPATIBILITY ===
PayrollRunCreated = PayrollRunCreatedEvent
PayrollRunProcessed = PayrollRunCalculatedEvent
PayrollRunPosted = PayrollRunPostedEvent
PayslipGenerated = PayslipGeneratedEvent
PayslipSentToEmployee = PayslipSentToEmployeeEvent
# Tambahan alias untuk event yang digunakan di service (tanpa akhiran Event)
PayrollRunApproved = PayrollRunApprovedEvent
PayrollRunCancelled = PayrollRunCancelledEvent
PayrollRunPaid = PayrollRunPaidEvent
EmployeeStructureUpdated = EmployeeStructureUpdatedEvent
SalaryComponentAdded = SalaryComponentAddedEvent


# === 4. DOMAIN EVENT PUBLISHER PROTOCOL ===


class DomainEventPublisher:
    """
    Protocol untuk publish domain events Payroll.
    """

    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)


# === 5. EXPORTS ===

__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "EmployeeStructureUpdatedEvent",
    "PayrollRunApprovedEvent",
    "PayrollRunCalculatedEvent",
    "PayrollRunCancelledEvent",
    "PayrollRunCreated",
    "PayrollRunCreatedEvent",
    "PayrollRunPaidEvent",
    "PayrollRunPosted",
    "PayrollRunPostedEvent",
    "PayrollRunProcessed",
    "PayslipGenerated",
    "PayslipGeneratedEvent",
    "PayslipSentToEmployee",
    "PayslipSentToEmployeeEvent",
    "SalaryComponentAddedEvent",
    # Alias tambahan untuk kompatibilitas
    "PayrollRunApproved",
    "PayrollRunCancelled",
    "PayrollRunPaid",
    "EmployeeStructureUpdated",
    "SalaryComponentAdded",
]
