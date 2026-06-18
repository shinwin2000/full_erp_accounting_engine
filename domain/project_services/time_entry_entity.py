#!/usr/bin/env python3
"""
Module: time_entry_entity.py
Layer: 6 - Domain / Project & Services
Responsibility: Entri waktu kerja.
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


class TimeEntryStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    BILLED = "billed"

    @classmethod
    def from_string(cls, value: str) -> TimeEntryStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


class WorkType(Enum):
    REGULAR = "regular"
    OVERTIME = "overtime"
    HOLIDAY = "holiday"
    TRAVEL = "travel"

    @classmethod
    def from_string(cls, value: str) -> WorkType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.REGULAR


@dataclass
class TimeEntryEntity:
    entry_id: UUID
    entry_number: str
    project_id: UUID
    project_code: str
    project_name: str
    employee_id: UUID
    employee_name: str
    entry_date: datetime
    hours: Decimal
    hourly_rate: Decimal
    work_type: WorkType
    status: TimeEntryStatus
    description: str = ""
    billable: bool = True
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self.entry_number or len(self.entry_number.strip()) < 3:
            raise ValueError("Entry number must be at least 3 characters")
        if self.hours <= 0:
            raise ValueError(f"Hours must be positive: {self.hours}")
        if self.hours > 24:
            raise ValueError(f"Hours cannot exceed 24 per day: {self.hours}")
        if self.hourly_rate < 0:
            raise ValueError(f"Hourly rate cannot be negative: {self.hourly_rate}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if self.entry_date.tzinfo is None:
            raise ValueError("entry_date must be timezone-aware")
        if self.approved_at and self.approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")

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

    @property
    def amount(self) -> Decimal:
        return (self.hours * self.hourly_rate).quantize(Decimal("0.01"))

    @property
    def billable_amount(self) -> Decimal:
        return self.amount if self.billable else Decimal(0)

    def submit(self, submitted_by: str) -> TimeEntryEntity:
        if self.status != TimeEntryStatus.DRAFT:
            raise ValueError(f"Cannot submit time entry in status {self.status.value}")
        self._record_audit("submitted", submitted_by, {})
        return TimeEntryEntity(
            entry_id=self.entry_id,
            entry_number=self.entry_number,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            entry_date=self.entry_date,
            hours=self.hours,
            hourly_rate=self.hourly_rate,
            work_type=self.work_type,
            status=TimeEntryStatus.SUBMITTED,
            description=self.description,
            billable=self.billable,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=submitted_by,
            version=self.version + 1,
        )

    def approve(self, approved_by: str) -> TimeEntryEntity:
        if self.status != TimeEntryStatus.SUBMITTED:
            raise ValueError(f"Cannot approve time entry in status {self.status.value}")
        self._record_audit("approved", approved_by, {})
        return TimeEntryEntity(
            entry_id=self.entry_id,
            entry_number=self.entry_number,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            entry_date=self.entry_date,
            hours=self.hours,
            hourly_rate=self.hourly_rate,
            work_type=self.work_type,
            status=TimeEntryStatus.APPROVED,
            description=self.description,
            billable=self.billable,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def reject(self, rejected_by: str, reason: str) -> TimeEntryEntity:
        if self.status != TimeEntryStatus.SUBMITTED:
            raise ValueError(f"Cannot reject time entry in status {self.status.value}")
        self._record_audit("rejected", rejected_by, {"reason": reason})
        return TimeEntryEntity(
            entry_id=self.entry_id,
            entry_number=self.entry_number,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            entry_date=self.entry_date,
            hours=self.hours,
            hourly_rate=self.hourly_rate,
            work_type=self.work_type,
            status=TimeEntryStatus.REJECTED,
            description=f"{self.description}\nRejected: {reason}",
            billable=self.billable,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=rejected_by,
            version=self.version + 1,
        )

    def mark_billed(self, billed_by: str) -> TimeEntryEntity:
        if self.status != TimeEntryStatus.APPROVED:
            raise ValueError(f"Cannot mark time entry as billed in status {self.status.value}")
        self._record_audit("marked_billed", billed_by, {})
        return TimeEntryEntity(
            entry_id=self.entry_id,
            entry_number=self.entry_number,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            entry_date=self.entry_date,
            hours=self.hours,
            hourly_rate=self.hourly_rate,
            work_type=self.work_type,
            status=TimeEntryStatus.BILLED,
            description=self.description,
            billable=self.billable,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=billed_by,
            version=self.version + 1,
        )

    def update_hours(self, new_hours: Decimal, updated_by: str) -> TimeEntryEntity:
        if new_hours <= 0:
            raise ValueError("Hours must be positive")
        if new_hours > 24:
            raise ValueError("Hours cannot exceed 24 per day")
        self._record_audit(
            "hours_updated", updated_by, {"old_hours": str(self.hours), "new_hours": str(new_hours)}
        )
        return TimeEntryEntity(
            entry_id=self.entry_id,
            entry_number=self.entry_number,
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            entry_date=self.entry_date,
            hours=new_hours,
            hourly_rate=self.hourly_rate,
            work_type=self.work_type,
            status=self.status,
            description=self.description,
            billable=self.billable,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "entry_number": self.entry_number,
            "project_id": str(self.project_id),
            "project_code": self.project_code,
            "project_name": self.project_name,
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "entry_date": self.entry_date.isoformat(),
            "hours": str(self.hours),
            "hourly_rate": str(self.hourly_rate),
            "amount": str(self.amount),
            "billable_amount": str(self.billable_amount),
            "work_type": self.work_type.value,
            "status": self.status.value,
            "description": self.description,
            "billable": self.billable,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeEntryEntity:
        return cls(
            entry_id=UUID(data["entry_id"]),
            entry_number=data["entry_number"],
            project_id=UUID(data["project_id"]),
            project_code=data["project_code"],
            project_name=data["project_name"],
            employee_id=UUID(data["employee_id"]),
            employee_name=data["employee_name"],
            entry_date=datetime.fromisoformat(data["entry_date"]),
            hours=Decimal(data["hours"]),
            hourly_rate=Decimal(data["hourly_rate"]),
            work_type=WorkType.from_string(data["work_type"]),
            status=TimeEntryStatus.from_string(data["status"]),
            description=data.get("description", ""),
            billable=data.get("billable", True),
            approved_by=data.get("approved_by"),
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        entry_number: str,
        project_id: UUID,
        project_code: str,
        project_name: str,
        employee_id: UUID,
        employee_name: str,
        entry_date: datetime,
        hours: Decimal,
        hourly_rate: Decimal,
        created_by: str,
        work_type: WorkType = WorkType.REGULAR,
        description: str = "",
        billable: bool = True,
    ) -> TimeEntryEntity:
        return cls(
            entry_id=uuid4(),
            entry_number=entry_number,
            project_id=project_id,
            project_code=project_code,
            project_name=project_name,
            employee_id=employee_id,
            employee_name=employee_name,
            entry_date=entry_date,
            hours=hours,
            hourly_rate=hourly_rate,
            work_type=work_type,
            status=TimeEntryStatus.DRAFT,
            description=description,
            billable=billable,
            created_by=created_by,
        )


TimeEntry = TimeEntryEntity


class TimeEntryRepository:
    async def get_by_id(self, entry_id: UUID, legal_entity_id: UUID) -> TimeEntryEntity | None:
        raise NotImplementedError

    async def get_by_employee(
        self,
        employee_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[TimeEntryEntity]:
        raise NotImplementedError

    async def get_by_project(
        self, project_id: UUID, legal_entity_id: UUID, status: TimeEntryStatus | None = None
    ) -> list[TimeEntryEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self, legal_entity_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[TimeEntryEntity]:
        raise NotImplementedError

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[TimeEntryEntity]:
        raise NotImplementedError

    async def save(self, time_entry: TimeEntryEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, entry_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "TimeEntry",
    "TimeEntryEntity",
    "TimeEntryRepository",
    "TimeEntryStatus",
    "WorkType",
]
