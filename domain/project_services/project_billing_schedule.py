#!/usr/bin/env python3
"""
Module: project_billing_schedule.py
Layer: 6 - Domain / Project & Services
Responsibility: Jadwal penagihan proyek.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class BillingType(Enum):
    MILESTONE = "milestone"
    TIME_BASED = "time_based"
    PROGRESS_BASED = "progress_based"
    RETAINER = "retainer"

    @classmethod
    def from_string(cls, value: str) -> BillingType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.MILESTONE


class BillingMilestoneStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    BILLED = "billed"
    PAID = "paid"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> BillingMilestoneStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.PENDING


@dataclass
class BillingMilestone:
    milestone_id: UUID
    milestone_name: str
    milestone_order: int
    amount: Decimal
    percentage: Decimal
    due_date: datetime
    status: BillingMilestoneStatus
    description: str = ""
    invoice_id: UUID | None = None
    invoice_number: str | None = None
    billed_at: datetime | None = None
    paid_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Milestone amount must be positive: {self.amount}")
        if not (0 <= self.percentage <= 100):
            raise ValueError(f"Percentage must be between 0 and 100: {self.percentage}")
        if self.due_date.tzinfo is None:
            raise ValueError("due_date must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": str(self.milestone_id),
            "milestone_name": self.milestone_name,
            "milestone_order": self.milestone_order,
            "amount": str(self.amount),
            "percentage": str(self.percentage),
            "due_date": self.due_date.isoformat(),
            "status": self.status.value,
            "description": self.description,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "invoice_number": self.invoice_number,
            "billed_at": self.billed_at.isoformat() if self.billed_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillingMilestone:
        return cls(
            milestone_id=UUID(data["milestone_id"]),
            milestone_name=data["milestone_name"],
            milestone_order=data["milestone_order"],
            amount=Decimal(data["amount"]),
            percentage=Decimal(data["percentage"]),
            due_date=datetime.fromisoformat(data["due_date"]),
            status=BillingMilestoneStatus.from_string(data["status"]),
            description=data.get("description", ""),
            invoice_id=UUID(data["invoice_id"]) if data.get("invoice_id") else None,
            invoice_number=data.get("invoice_number"),
            billed_at=datetime.fromisoformat(data["billed_at"]) if data.get("billed_at") else None,
            paid_at=datetime.fromisoformat(data["paid_at"]) if data.get("paid_at") else None,
        )


@dataclass
class ProjectBillingSchedule:
    schedule_id: UUID
    project_id: UUID
    project_code: str
    project_name: str
    billing_type: BillingType
    milestones: list[BillingMilestone] = field(default_factory=list)
    total_amount: Decimal = Decimal(0)
    total_billed: Decimal = Decimal(0)
    total_paid: Decimal = Decimal(0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    def _record_audit(self, action: str, user_id: str, details: dict | None = None) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    @classmethod
    def create_milestone_schedule(
        cls,
        project_id: UUID,
        project_code: str,
        project_name: str,
        milestones: list[BillingMilestone],
        created_by: str,
    ) -> ProjectBillingSchedule:
        total = sum(m.amount for m in milestones)
        instance = cls(
            schedule_id=uuid4(),
            project_id=project_id,
            project_code=project_code,
            project_name=project_name,
            billing_type=BillingType.MILESTONE,
            milestones=milestones,
            total_amount=total,
            created_by=created_by,
        )
        instance._record_audit("created", created_by, {"total_amount": str(total)})
        return instance

    def add_milestone(self, milestone: BillingMilestone, added_by: str) -> ProjectBillingSchedule:
        new_milestones = self.milestones + [milestone]
        new_total = sum(m.amount for m in new_milestones)
        self._record_audit(
            "milestone_added",
            added_by,
            {"milestone_name": milestone.milestone_name, "amount": str(milestone.amount)},
        )
        return ProjectBillingSchedule(
            schedule_id=self.schedule_id,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            billing_type=self.billing_type,
            milestones=new_milestones,
            total_amount=new_total,
            total_billed=self.total_billed,
            total_paid=self.total_paid,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_milestone(self, milestone_id: UUID, removed_by: str) -> ProjectBillingSchedule:
        milestone_to_remove = next(
            (m for m in self.milestones if m.milestone_id == milestone_id), None
        )
        if not milestone_to_remove:
            raise ValueError(f"Milestone {milestone_id} not found")
        new_milestones = [m for m in self.milestones if m.milestone_id != milestone_id]
        new_total = sum(m.amount for m in new_milestones)
        self._record_audit(
            "milestone_removed", removed_by, {"milestone_name": milestone_to_remove.milestone_name}
        )
        return ProjectBillingSchedule(
            schedule_id=self.schedule_id,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            billing_type=self.billing_type,
            milestones=new_milestones,
            total_amount=new_total,
            total_billed=self.total_billed,
            total_paid=self.total_paid,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def mark_milestone_ready(self, milestone_id: UUID, marked_by: str) -> ProjectBillingSchedule:
        new_milestones = []
        milestone_found = False
        for m in self.milestones:
            if m.milestone_id == milestone_id and m.status == BillingMilestoneStatus.PENDING:
                new_milestones.append(
                    BillingMilestone(
                        milestone_id=m.milestone_id,
                        milestone_name=m.milestone_name,
                        milestone_order=m.milestone_order,
                        amount=m.amount,
                        percentage=m.percentage,
                        due_date=m.due_date,
                        status=BillingMilestoneStatus.READY,
                        description=m.description,
                        invoice_id=m.invoice_id,
                        invoice_number=m.invoice_number,
                        billed_at=m.billed_at,
                        paid_at=m.paid_at,
                    )
                )
                milestone_found = True
            else:
                new_milestones.append(m)
        if not milestone_found:
            raise ValueError(f"Milestone {milestone_id} not found or not in PENDING status")
        self._record_audit("milestone_marked_ready", marked_by, {"milestone_id": str(milestone_id)})
        return ProjectBillingSchedule(
            schedule_id=self.schedule_id,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            billing_type=self.billing_type,
            milestones=new_milestones,
            total_amount=self.total_amount,
            total_billed=self.total_billed,
            total_paid=self.total_paid,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=marked_by,
            version=self.version + 1,
        )

    def record_billing(
        self, milestone_id: UUID, invoice_id: UUID, invoice_number: str, billed_by: str
    ) -> ProjectBillingSchedule:
        new_milestones = []
        billed_amount = Decimal(0)
        milestone_found = False
        for m in self.milestones:
            if m.milestone_id == milestone_id and m.status == BillingMilestoneStatus.READY:
                new_milestones.append(
                    BillingMilestone(
                        milestone_id=m.milestone_id,
                        milestone_name=m.milestone_name,
                        milestone_order=m.milestone_order,
                        amount=m.amount,
                        percentage=m.percentage,
                        due_date=m.due_date,
                        status=BillingMilestoneStatus.BILLED,
                        description=m.description,
                        invoice_id=invoice_id,
                        invoice_number=invoice_number,
                        billed_at=datetime.now(UTC),
                        paid_at=m.paid_at,
                    )
                )
                billed_amount = m.amount
                milestone_found = True
            else:
                new_milestones.append(m)
        if not milestone_found:
            raise ValueError(f"Milestone {milestone_id} not found or not in READY status")
        new_total_billed = self.total_billed + billed_amount
        self._record_audit(
            "billing_recorded",
            billed_by,
            {"milestone_id": str(milestone_id), "amount": str(billed_amount)},
        )
        return ProjectBillingSchedule(
            schedule_id=self.schedule_id,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            billing_type=self.billing_type,
            milestones=new_milestones,
            total_amount=self.total_amount,
            total_billed=new_total_billed,
            total_paid=self.total_paid,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=billed_by,
            version=self.version + 1,
        )

    def record_payment(self, milestone_id: UUID, paid_by: str) -> ProjectBillingSchedule:
        new_milestones = []
        paid_amount = Decimal(0)
        milestone_found = False
        for m in self.milestones:
            if m.milestone_id == milestone_id and m.status == BillingMilestoneStatus.BILLED:
                new_milestones.append(
                    BillingMilestone(
                        milestone_id=m.milestone_id,
                        milestone_name=m.milestone_name,
                        milestone_order=m.milestone_order,
                        amount=m.amount,
                        percentage=m.percentage,
                        due_date=m.due_date,
                        status=BillingMilestoneStatus.PAID,
                        description=m.description,
                        invoice_id=m.invoice_id,
                        invoice_number=m.invoice_number,
                        billed_at=m.billed_at,
                        paid_at=datetime.now(UTC),
                    )
                )
                paid_amount = m.amount
                milestone_found = True
            else:
                new_milestones.append(m)
        if not milestone_found:
            raise ValueError(f"Milestone {milestone_id} not found or not in BILLED status")
        new_total_paid = self.total_paid + paid_amount
        self._record_audit(
            "payment_recorded",
            paid_by,
            {"milestone_id": str(milestone_id), "amount": str(paid_amount)},
        )
        return ProjectBillingSchedule(
            schedule_id=self.schedule_id,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            billing_type=self.billing_type,
            milestones=new_milestones,
            total_amount=self.total_amount,
            total_billed=self.total_billed,
            total_paid=new_total_paid,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=paid_by,
            version=self.version + 1,
        )

    def get_outstanding_billing(self) -> Decimal:
        return self.total_billed - self.total_paid

    def get_ready_to_bill(self) -> Decimal:
        total = Decimal(0)
        for m in self.milestones:
            if m.status == BillingMilestoneStatus.READY:
                total += m.amount
        return total

    def get_upcoming_billing(self, days_ahead: int = 30) -> list[BillingMilestone]:
        today = datetime.now(UTC)
        cutoff = (
            today.replace(day=today.day + days_ahead)
            if today.day + days_ahead <= 31
            else today + timedelta(days=days_ahead)
        )
        return [
            m
            for m in self.milestones
            if m.status == BillingMilestoneStatus.PENDING and m.due_date <= cutoff
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": str(self.schedule_id),
            "project_id": str(self.project_id),
            "project_code": self.project_code,
            "project_name": self.project_name,
            "billing_type": self.billing_type.value,
            "total_amount": str(self.total_amount),
            "total_billed": str(self.total_billed),
            "total_paid": str(self.total_paid),
            "outstanding_billing": str(self.get_outstanding_billing()),
            "ready_to_bill": str(self.get_ready_to_bill()),
            "milestones": [m.to_dict() for m in self.milestones],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectBillingSchedule:
        milestones = [BillingMilestone.from_dict(m) for m in data.get("milestones", [])]
        return cls(
            schedule_id=UUID(data["schedule_id"]),
            project_id=UUID(data["project_id"]),
            project_code=data["project_code"],
            project_name=data["project_name"],
            billing_type=BillingType.from_string(data["billing_type"]),
            milestones=milestones,
            total_amount=Decimal(data["total_amount"]),
            total_billed=Decimal(data["total_billed"]),
            total_paid=Decimal(data["total_paid"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )


class ProjectBillingScheduleRepository:
    async def get_by_project(
        self, project_id: UUID, legal_entity_id: UUID
    ) -> ProjectBillingSchedule | None:
        raise NotImplementedError

    async def save(self, schedule: ProjectBillingSchedule, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, schedule_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "BillingMilestone",
    "BillingMilestoneStatus",
    "BillingType",
    "ProjectBillingSchedule",
    "ProjectBillingScheduleRepository",
]
