#!/usr/bin/env python3
"""
Module: project_entity.py
Layer: 6 - Domain / Project & Services
Responsibility: Entitas proyek.
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


class ProjectStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> ProjectStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


class ProjectType(Enum):
    CONSTRUCTION = "construction"
    CONSULTING = "consulting"
    DEVELOPMENT = "development"
    MAINTENANCE = "maintenance"
    RESEARCH = "research"
    OTHER = "other"

    @classmethod
    def from_string(cls, value: str) -> ProjectType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.OTHER


@dataclass
class ProjectEntity:
    project_id: UUID
    project_code: str
    project_name: str
    project_type: ProjectType
    status: ProjectStatus
    customer_id: UUID
    customer_name: str
    contract_value: Decimal
    currency: str
    start_date: datetime
    expected_end_date: datetime
    actual_end_date: datetime | None = None
    contract_number: str | None = None
    description: str = ""
    project_manager_id: UUID | None = None
    project_manager_name: str | None = None
    budget: Decimal = Decimal(0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)
    _events: list[Any] = field(default_factory=list, repr=False)  # Untuk event sourcing
    _snapshots: list[dict] = field(default_factory=list, repr=False)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.project_code or len(self.project_code.strip()) < 3:
            raise ValueError("Project code must be at least 3 characters")
        if not self.project_name or len(self.project_name.strip()) < 2:
            raise ValueError("Project name must be at least 2 characters")
        if self.contract_value < 0:
            raise ValueError(f"Contract value cannot be negative: {self.contract_value}")
        if self.expected_end_date <= self.start_date:
            raise ValueError("Expected end date must be after start date")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.expected_end_date.tzinfo is None:
            object.__setattr__(
                self, "expected_end_date", self.expected_end_date.replace(tzinfo=UTC)
            )
        if self.actual_end_date and self.actual_end_date.tzinfo is None:
            object.__setattr__(self, "actual_end_date", self.actual_end_date.replace(tzinfo=UTC))

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

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "project_id": str(self.project_id),
                "status": self.status.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    # ==================== PROPERTIES ====================

    @property
    def id(self) -> UUID:
        return self.project_id

    @property
    def is_active(self) -> bool:
        return self.status == ProjectStatus.ACTIVE

    @property
    def is_completed(self) -> bool:
        return self.status == ProjectStatus.COMPLETED

    @property
    def is_cancelled(self) -> bool:
        return self.status == ProjectStatus.CANCELLED

    @property
    def is_on_hold(self) -> bool:
        return self.status == ProjectStatus.ON_HOLD

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    # ==================== QUERY METHODS ====================

    def is_overdue(self, as_of: datetime | None = None) -> bool:
        if self.status in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
            return False
        check_date = as_of or datetime.now(UTC)
        return check_date > self.expected_end_date

    def get_duration_days(self) -> int:
        end_date = self.actual_end_date or self.expected_end_date
        return (end_date - self.start_date).days

    def get_remaining_days(self, as_of: datetime | None = None) -> int:
        if self.is_completed or self.is_cancelled:
            return 0
        check_date = as_of or datetime.now(UTC)
        if check_date > self.expected_end_date:
            return 0
        return (self.expected_end_date - check_date).days

    def get_completion_percentage(self) -> float:
        if self.is_completed:
            return 100.0
        if self.is_cancelled:
            return 0.0
        total_days = self.get_duration_days()
        if total_days <= 0:
            return 0.0
        elapsed_days = (datetime.now(UTC) - self.start_date).days
        return min(100.0, max(0.0, elapsed_days / total_days * 100))

    # ==================== VALIDATION ====================

    def validate(self) -> list[str]:
        errors = []
        if not self.project_code or len(self.project_code.strip()) < 3:
            errors.append("Project code must be at least 3 characters")
        if not self.project_name or len(self.project_name.strip()) < 2:
            errors.append("Project name must be at least 2 characters")
        if self.contract_value < 0:
            errors.append(f"Contract value cannot be negative: {self.contract_value}")
        if self.expected_end_date <= self.start_date:
            errors.append("Expected end date must be after start date")
        return errors

    # ==================== LOCK / UNLOCK ====================

    def lock(self, user_id: str, reason: str | None = None) -> ProjectEntity:
        if self._is_locked:
            raise ValueError(f"Project is already locked by {self._locked_by}")
        self._record_audit("locked", user_id, {"reason": reason})
        new = self._copy()
        new._is_locked = True
        new._locked_by = user_id
        new._locked_at = datetime.now(UTC)
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        return new

    def unlock(self, user_id: str) -> ProjectEntity:
        if not self._is_locked:
            raise ValueError("Project is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Project locked by {self._locked_by}, cannot unlock by {user_id}")
        self._record_audit("unlocked", user_id, {})
        new = self._copy()
        new._is_locked = False
        new._locked_by = None
        new._locked_at = None
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        return new

    # ==================== CLONE ====================

    def clone(self) -> ProjectEntity:
        self._record_audit("cloned", "system", {"source_id": str(self.project_id)})
        new = self._copy()
        new.project_id = uuid4()
        new.project_code = f"COPY-{self.project_code}"
        new.project_name = f"Copy of {self.project_name}"
        new.status = ProjectStatus.DRAFT
        new.version = 1
        new.created_at = datetime.now(UTC)
        new.updated_at = datetime.now(UTC)
        new.created_by = self.created_by
        new._audit_trail = []
        new._snapshots = []
        new._is_locked = False
        new._locked_by = None
        new._locked_at = None
        new.description = f"Copy of: {self.description}"
        return new

    def _copy(self) -> ProjectEntity:
        """Internal copy without generating new ID."""
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=self.status,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=self.actual_end_date,
            contract_number=self.contract_number,
            description=self.description,
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
            _is_locked=self._is_locked,
            _locked_by=self._locked_by,
            _locked_at=self._locked_at,
        )

    # ==================== STATUS TRANSITIONS ====================

    def activate(self, activated_by: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot activate locked project")
        if self.status != ProjectStatus.DRAFT:
            raise ValueError(f"Cannot activate project in status {self.status.value}")
        self._record_audit("activated", activated_by, {})
        new = self._copy()
        new.status = ProjectStatus.ACTIVE
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = activated_by
        return new

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot deactivate locked project")
        if self.status != ProjectStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate project in status {self.status.value}")
        self._record_audit("deactivated", deactivated_by, {"reason": reason})
        new = self._copy()
        new.status = ProjectStatus.DRAFT
        if reason:
            new.description = f"{self.description}\nDeactivated: {reason}"
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = deactivated_by
        return new

    def put_on_hold(self, put_by: str, reason: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot put locked project on hold")
        if self.status != ProjectStatus.ACTIVE:
            raise ValueError(f"Cannot put project on hold in status {self.status.value}")
        self._record_audit("put_on_hold", put_by, {"reason": reason})
        new = self._copy()
        new.status = ProjectStatus.ON_HOLD
        new.description = f"{self.description}\nOn hold: {reason}"
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = put_by
        return new

    def resume(self, resumed_by: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot resume locked project")
        if self.status != ProjectStatus.ON_HOLD:
            raise ValueError(f"Cannot resume project in status {self.status.value}")
        self._record_audit("resumed", resumed_by, {})
        new = self._copy()
        new.status = ProjectStatus.ACTIVE
        new.description = self.description.replace("On hold:", "Resumed:")
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = resumed_by
        return new

    def complete(self, completed_by: str, actual_end_date: datetime | None = None) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot complete locked project")
        if self.status not in (ProjectStatus.ACTIVE, ProjectStatus.ON_HOLD):
            raise ValueError(f"Cannot complete project in status {self.status.value}")
        self._record_audit(
            "completed",
            completed_by,
            {"actual_end_date": (actual_end_date or datetime.now(UTC)).isoformat()},
        )
        new = self._copy()
        new.status = ProjectStatus.COMPLETED
        new.actual_end_date = actual_end_date or datetime.now(UTC)
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = completed_by
        return new

    def cancel(self, cancelled_by: str, reason: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot cancel locked project")
        if self.status == ProjectStatus.COMPLETED:
            raise ValueError("Cannot cancel completed project")
        self._record_audit("cancelled", cancelled_by, {"reason": reason})
        new = self._copy()
        new.status = ProjectStatus.CANCELLED
        new.description = f"{self.description}\nCancelled: {reason}"
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = cancelled_by
        return new

    # ==================== UPDATE METHODS ====================

    def rename(self, new_name: str, updated_by: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot rename locked project")
        if not new_name or len(new_name.strip()) < 2:
            raise ValueError("Project name must be at least 2 characters")
        self._record_audit(
            "renamed", updated_by, {"old_name": self.project_name, "new_name": new_name}
        )
        new = self._copy()
        new.project_name = new_name
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = updated_by
        return new

    def update_dates(
        self,
        updated_by: str,
        new_start_date: datetime | None = None,
        new_expected_end_date: datetime | None = None,
    ) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot update dates of locked project")
        start = new_start_date or self.start_date
        end = new_expected_end_date or self.expected_end_date
        if end <= start:
            raise ValueError("Expected end date must be after start date")
        self._record_audit(
            "dates_updated",
            updated_by,
            {
                "old_start": self.start_date.isoformat(),
                "new_start": start.isoformat(),
                "old_end": self.expected_end_date.isoformat(),
                "new_end": end.isoformat(),
            },
        )
        new = self._copy()
        new.start_date = start
        new.expected_end_date = end
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = updated_by
        return new

    def update_budget(self, new_budget: Decimal, updated_by: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot update budget of locked project")
        if new_budget < 0:
            raise ValueError("Budget cannot be negative")
        self._record_audit(
            "budget_updated",
            updated_by,
            {"old_budget": str(self.budget), "new_budget": str(new_budget)},
        )
        new = self._copy()
        new.budget = new_budget
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = updated_by
        return new

    def update_project_manager(
        self, manager_id: UUID, manager_name: str, updated_by: str
    ) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot update project manager of locked project")
        self._record_audit(
            "project_manager_updated",
            updated_by,
            {
                "old_manager_id": str(self.project_manager_id) if self.project_manager_id else None,
                "new_manager_id": str(manager_id),
            },
        )
        new = self._copy()
        new.project_manager_id = manager_id
        new.project_manager_name = manager_name
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = updated_by
        return new

    def update_contract_value(self, new_value: Decimal, updated_by: str) -> ProjectEntity:
        if self._is_locked:
            raise ValueError("Cannot update contract value of locked project")
        if new_value < 0:
            raise ValueError("Contract value cannot be negative")
        self._record_audit(
            "contract_value_updated",
            updated_by,
            {"old_value": str(self.contract_value), "new_value": str(new_value)},
        )
        new = self._copy()
        new.contract_value = new_value
        new.version = self.version + 1
        new.updated_at = datetime.now(UTC)
        new.created_by = updated_by
        return new

    # ==================== DICTIONARY ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id),
            "project_code": self.project_code,
            "project_name": self.project_name,
            "project_type": self.project_type.value,
            "status": self.status.value,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "contract_value": str(self.contract_value),
            "currency": self.currency,
            "start_date": self.start_date.isoformat(),
            "expected_end_date": self.expected_end_date.isoformat(),
            "actual_end_date": self.actual_end_date.isoformat() if self.actual_end_date else None,
            "contract_number": self.contract_number,
            "description": self.description,
            "project_manager_id": str(self.project_manager_id) if self.project_manager_id else None,
            "project_manager_name": self.project_manager_name,
            "budget": str(self.budget),
            "is_overdue": self.is_overdue(),
            "duration_days": self.get_duration_days(),
            "completion_percentage": self.get_completion_percentage(),
            "remaining_days": self.get_remaining_days(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "is_locked": self._is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectEntity:
        return cls(
            project_id=UUID(data["project_id"]),
            project_code=data["project_code"],
            project_name=data["project_name"],
            project_type=ProjectType.from_string(data["project_type"]),
            status=ProjectStatus.from_string(data["status"]),
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            contract_value=Decimal(data["contract_value"]),
            currency=data["currency"],
            start_date=datetime.fromisoformat(data["start_date"]),
            expected_end_date=datetime.fromisoformat(data["expected_end_date"]),
            actual_end_date=datetime.fromisoformat(data["actual_end_date"])
            if data.get("actual_end_date")
            else None,
            contract_number=data.get("contract_number"),
            description=data.get("description", ""),
            project_manager_id=UUID(data["project_manager_id"])
            if data.get("project_manager_id")
            else None,
            project_manager_name=data.get("project_manager_name"),
            budget=Decimal(data.get("budget", "0")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        project_code: str,
        project_name: str,
        project_type: ProjectType,
        customer_id: UUID,
        customer_name: str,
        contract_value: Decimal,
        currency: str,
        start_date: datetime,
        expected_end_date: datetime,
        created_by: str,
        budget: Decimal = Decimal(0),
        contract_number: str | None = None,
        description: str = "",
        project_manager_id: UUID | None = None,
        project_manager_name: str | None = None,
    ) -> ProjectEntity:
        """Factory method to create a new project entity."""
        return cls(
            project_id=uuid4(),
            project_code=project_code,
            project_name=project_name,
            project_type=project_type,
            status=ProjectStatus.DRAFT,
            customer_id=customer_id,
            customer_name=customer_name,
            contract_value=contract_value,
            currency=currency,
            start_date=start_date,
            expected_end_date=expected_end_date,
            contract_number=contract_number,
            description=description,
            project_manager_id=project_manager_id,
            project_manager_name=project_manager_name,
            budget=budget,
            created_by=created_by,
        )


# Alias
Project = ProjectEntity


class ProjectEntityRepository:
    """Repository interface for ProjectEntity."""

    async def get_by_id(self, project_id: UUID, legal_entity_id: UUID) -> ProjectEntity | None:
        raise NotImplementedError

    async def get_by_code(self, project_code: str, legal_entity_id: UUID) -> ProjectEntity | None:
        raise NotImplementedError

    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, status: ProjectStatus | None = None
    ) -> list[ProjectEntity]:
        raise NotImplementedError

    async def get_by_status(
        self, legal_entity_id: UUID, status: ProjectStatus
    ) -> list[ProjectEntity]:
        raise NotImplementedError

    async def get_overdue(
        self, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> list[ProjectEntity]:
        raise NotImplementedError

    async def save(self, project: ProjectEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, project_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "Project",
    "ProjectEntity",
    "ProjectEntityRepository",
    "ProjectStatus",
    "ProjectType",
]
