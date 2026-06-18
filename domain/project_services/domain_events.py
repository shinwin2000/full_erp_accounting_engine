#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Project & Services
Responsibility: Event: ProjectCreated, MilestoneReached, TimeEntryApproved, etc.
               Mendefinisikan semua domain events yang dihasilkan oleh
               Project & Services aggregates. Event ini digunakan untuk
               komunikasi antar bounded context, event sourcing, dan
               proyeksi read model.

Dependencies:
- standard library (uuid, datetime, dataclass, json)
- domain.project_services.project_entity (ProjectEntity)
- domain.project_services.time_entry_entity (TimeEntryEntity)
- domain.project_services.project_billing_schedule (ProjectBillingSchedule)

Audit: Setiap event domain project & services dictat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.project_services.project_entity import ProjectEntity, ProjectStatus
from domain.project_services.time_entry_entity import TimeEntryEntity

# === 1. DOMAIN EVENT BASE ===


class DomainEventType(Enum):
    """Tipe domain event untuk Project & Services."""

    PROJECT_CREATED = "project_created"
    PROJECT_ACTIVATED = "project_activated"
    PROJECT_COMPLETED = "project_completed"
    PROJECT_CANCELLED = "project_cancelled"
    PROJECT_ON_HOLD = "project_on_hold"
    PROJECT_RESUMED = "project_resumed"

    COST_ADDED = "cost_added"
    REVENUE_RECOGNIZED = "revenue_recognized"

    MILESTONE_READY = "milestone_ready"
    MILESTONE_BILLED = "milestone_billed"
    MILESTONE_PAID = "milestone_paid"

    TIME_ENTRY_SUBMITTED = "time_entry_submitted"
    TIME_ENTRY_APPROVED = "time_entry_approved"
    TIME_ENTRY_REJECTED = "time_entry_rejected"

    RETAINER_CONTRACT_ACTIVATED = "retainer_contract_activated"
    RETAINER_CONTRACT_TERMINATED = "retainer_contract_terminated"

    PROJECT_BILLING_GENERATED = "project_billing_generated"


@dataclass
class DomainEvent:
    """
    Base class untuk semua domain events Project & Services.
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
class ProjectCreatedEvent(DomainEvent):
    """Event ketika proyek baru dibuat."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project: ProjectEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project.project_id),
            "project_code": project.project_code,
            "project_name": project.project_name,
            "project_type": project.project_type.value,
            "customer_id": str(project.customer_id),
            "customer_name": project.customer_name,
            "contract_value": str(project.contract_value),
            "currency": project.currency,
            "start_date": project.start_date.isoformat(),
            "expected_end_date": project.expected_end_date.isoformat(),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PROJECT_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class ProjectActivatedEvent(DomainEvent):
    """Event ketika proyek diaktifkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project: ProjectEntity,
        activated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project.project_id),
            "project_code": project.project_code,
            "project_name": project.project_name,
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PROJECT_ACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class ProjectCompletedEvent(DomainEvent):
    """Event ketika proyek selesai."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project: ProjectEntity,
        completed_by: str,
        actual_end_date: datetime,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project.project_id),
            "project_code": project.project_code,
            "project_name": project.project_name,
            "completed_by": completed_by,
            "actual_end_date": actual_end_date.isoformat(),
            "final_status": ProjectStatus.COMPLETED.value,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PROJECT_COMPLETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class RevenueRecognizedEvent(DomainEvent):
    """Event ketika pendapatan proyek diakui."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project_id: UUID,
        project_code: str,
        period_start: datetime,
        period_end: datetime,
        recognized_revenue: Decimal,
        recognized_cost: Decimal,
        recognized_profit: Decimal,
        cumulative_percentage: Decimal,
        recognized_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project_id),
            "project_code": project_code,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "recognized_revenue": str(recognized_revenue),
            "recognized_cost": str(recognized_cost),
            "recognized_profit": str(recognized_profit),
            "cumulative_percentage": str(cumulative_percentage),
            "recognized_by": recognized_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.REVENUE_RECOGNIZED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class ProjectBillingGeneratedEvent(DomainEvent):
    """Event ketika billing proyek dihasilkan (invoice)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project_id: UUID,
        invoice_id: UUID,
        invoice_number: str,
        amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project_id),
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "amount": str(amount),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PROJECT_BILLING_GENERATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class MilestoneReadyEvent(DomainEvent):
    """Event ketika milestone siap ditagih."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project_id: UUID,
        project_code: str,
        milestone_id: UUID,
        milestone_name: str,
        amount: Decimal,
        due_date: datetime,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project_id),
            "project_code": project_code,
            "milestone_id": str(milestone_id),
            "milestone_name": milestone_name,
            "amount": str(amount),
            "due_date": due_date.isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.MILESTONE_READY,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class MilestoneBilledEvent(DomainEvent):
    """Event ketika milestone telah ditagih."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        project_id: UUID,
        project_code: str,
        milestone_id: UUID,
        milestone_name: str,
        amount: Decimal,
        invoice_id: UUID,
        invoice_number: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "project_id": str(project_id),
            "project_code": project_code,
            "milestone_id": str(milestone_id),
            "milestone_name": milestone_name,
            "amount": str(amount),
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.MILESTONE_BILLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class TimeEntrySubmittedEvent(DomainEvent):
    """Event ketika time entry disubmit."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        time_entry: TimeEntryEntity,
        submitted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "entry_id": str(time_entry.entry_id),
            "entry_number": time_entry.entry_number,
            "project_id": str(time_entry.project_id),
            "project_code": time_entry.project_code,
            "employee_id": str(time_entry.employee_id),
            "employee_name": time_entry.employee_name,
            "entry_date": time_entry.entry_date.isoformat(),
            "hours": str(time_entry.hours),
            "amount": str(time_entry.amount),
            "submitted_by": submitted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TIME_ENTRY_SUBMITTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class TimeEntryApprovedEvent(DomainEvent):
    """Event ketika time entry disetujui."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        time_entry: TimeEntryEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "entry_id": str(time_entry.entry_id),
            "entry_number": time_entry.entry_number,
            "project_id": str(time_entry.project_id),
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TIME_ENTRY_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class RetainerContractActivatedEvent(DomainEvent):
    """Event ketika kontrak retainer diaktifkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        contract: RetainerContractEntity,
        activated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "contract_id": str(contract.contract_id),
            "contract_number": contract.contract_number,
            "customer_id": str(contract.customer_id),
            "customer_name": contract.customer_name,
            "monthly_fee": str(contract.monthly_fee),
            "allocated_hours": str(contract.allocated_hours),
            "start_date": contract.start_date.isoformat(),
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.RETAINER_CONTRACT_ACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# === 3. ALIASES FOR SERVICE LAYER COMPATIBILITY ===

ProjectCreated = ProjectCreatedEvent
ProjectCompleted = ProjectCompletedEvent
RevenueRecognized = RevenueRecognizedEvent
TimeEntryRecorded = TimeEntrySubmittedEvent
ProjectBillingGenerated = ProjectBillingGeneratedEvent


# === 4. DOMAIN EVENT PUBLISHER PROTOCOL ===


class DomainEventPublisher:
    """
    Protocol untuk publish domain events Project & Services.
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
    "MilestoneBilledEvent",
    "MilestoneReadyEvent",
    "ProjectActivatedEvent",
    "ProjectCompletedEvent",
    "ProjectCreatedEvent",
    "ProjectBillingGeneratedEvent",
    "RetainerContractActivatedEvent",
    "RevenueRecognizedEvent",
    "TimeEntryApprovedEvent",
    "TimeEntrySubmittedEvent",
    # Aliases
    "ProjectCreated",
    "ProjectCompleted",
    "RevenueRecognized",
    "TimeEntryRecorded",
    "ProjectBillingGenerated",
]
