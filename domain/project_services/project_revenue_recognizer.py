#!/usr/bin/env python3
"""
Module: project_revenue_recognizer.py
Layer: 6 - Domain / Project & Services
Responsibility: Project entity (ProjectEntity) AND Revenue recognition logic (ProjectRevenueRecognizer).
Note: This file originally contained only ProjectEntity. It has been extended with
      ProjectRevenueRecognizer to fix the import error in aggregate_root.py.
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


# =============================================================================
#  ENUMS (preserved from original)
# =============================================================================


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


class CostType(Enum):
    """Cost type enumeration – used in CostEntry (referenced by aggregate_root)."""

    LABOR = "labor"
    MATERIAL = "material"
    EQUIPMENT = "equipment"
    SUBCONTRACTOR = "subcontractor"
    OTHER = "other"


# =============================================================================
#  PROJECT ENTITY (fully preserved from original)
# =============================================================================


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
        # Normalize timezones
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

    # ==================== CLONE ====================
    def clone(self) -> ProjectEntity:
        self._record_audit("cloned", "system", {"source_id": str(self.project_id)})
        return ProjectEntity(
            project_id=uuid4(),
            project_code=f"COPY-{self.project_code}",
            project_name=f"Copy of {self.project_name}",
            project_type=self.project_type,
            status=ProjectStatus.DRAFT,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=None,
            contract_number=self.contract_number,
            description=f"Copy of: {self.description}",
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_by=self.created_by,
            version=1,
        )

    # ==================== STATUS TRANSITIONS ====================
    def activate(self, activated_by: str) -> ProjectEntity:
        if self.status != ProjectStatus.DRAFT:
            raise ValueError(f"Cannot activate project in status {self.status.value}")
        self._record_audit("activated", activated_by, {})
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=ProjectStatus.ACTIVE,
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
            updated_at=datetime.now(UTC),
            created_by=activated_by,
            version=self.version + 1,
        )

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ProjectEntity:
        if self.status != ProjectStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate project in status {self.status.value}")
        self._record_audit("deactivated", deactivated_by, {"reason": reason})
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=ProjectStatus.DRAFT,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=self.actual_end_date,
            contract_number=self.contract_number,
            description=f"{self.description}\nDeactivated: {reason}"
            if reason
            else self.description,
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=deactivated_by,
            version=self.version + 1,
        )

    def put_on_hold(self, put_by: str, reason: str) -> ProjectEntity:
        if self.status != ProjectStatus.ACTIVE:
            raise ValueError(f"Cannot put project on hold in status {self.status.value}")
        self._record_audit("put_on_hold", put_by, {"reason": reason})
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=ProjectStatus.ON_HOLD,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=self.actual_end_date,
            contract_number=self.contract_number,
            description=f"{self.description}\nOn hold: {reason}",
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=put_by,
            version=self.version + 1,
        )

    def resume(self, resumed_by: str) -> ProjectEntity:
        if self.status != ProjectStatus.ON_HOLD:
            raise ValueError(f"Cannot resume project in status {self.status.value}")
        self._record_audit("resumed", resumed_by, {})
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=ProjectStatus.ACTIVE,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=self.actual_end_date,
            contract_number=self.contract_number,
            description=self.description.replace("On hold:", "Resumed:"),
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=resumed_by,
            version=self.version + 1,
        )

    def complete(self, completed_by: str, actual_end_date: datetime | None = None) -> ProjectEntity:
        if self.status not in (ProjectStatus.ACTIVE, ProjectStatus.ON_HOLD):
            raise ValueError(f"Cannot complete project in status {self.status.value}")
        self._record_audit(
            "completed",
            completed_by,
            {"actual_end_date": (actual_end_date or datetime.now(UTC)).isoformat()},
        )
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=ProjectStatus.COMPLETED,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=actual_end_date or datetime.now(UTC),
            contract_number=self.contract_number,
            description=self.description,
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=completed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> ProjectEntity:
        if self.status == ProjectStatus.COMPLETED:
            raise ValueError("Cannot cancel completed project")
        self._record_audit("cancelled", cancelled_by, {"reason": reason})
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=self.project_name,
            project_type=self.project_type,
            status=ProjectStatus.CANCELLED,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            contract_value=self.contract_value,
            currency=self.currency,
            start_date=self.start_date,
            expected_end_date=self.expected_end_date,
            actual_end_date=self.actual_end_date,
            contract_number=self.contract_number,
            description=f"{self.description}\nCancelled: {reason}",
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
        )

    # ==================== UPDATE METHODS ====================
    def rename(self, new_name: str, updated_by: str) -> ProjectEntity:
        if not new_name or len(new_name.strip()) < 2:
            raise ValueError("Project name must be at least 2 characters")
        self._record_audit(
            "renamed", updated_by, {"old_name": self.project_name, "new_name": new_name}
        )
        return ProjectEntity(
            project_id=self.project_id,
            project_code=self.project_code,
            project_name=new_name,
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
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_dates(
        self,
        updated_by: str,
        new_start_date: datetime | None = None,
        new_expected_end_date: datetime | None = None,
    ) -> ProjectEntity:
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
            start_date=start,
            expected_end_date=end,
            actual_end_date=self.actual_end_date,
            contract_number=self.contract_number,
            description=self.description,
            project_manager_id=self.project_manager_id,
            project_manager_name=self.project_manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_budget(self, new_budget: Decimal, updated_by: str) -> ProjectEntity:
        if new_budget < 0:
            raise ValueError("Budget cannot be negative")
        self._record_audit(
            "budget_updated",
            updated_by,
            {"old_budget": str(self.budget), "new_budget": str(new_budget)},
        )
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
            budget=new_budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_project_manager(
        self, manager_id: UUID, manager_name: str, updated_by: str
    ) -> ProjectEntity:
        self._record_audit(
            "project_manager_updated",
            updated_by,
            {
                "old_manager_id": str(self.project_manager_id) if self.project_manager_id else None,
                "new_manager_id": str(manager_id),
            },
        )
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
            project_manager_id=manager_id,
            project_manager_name=manager_name,
            budget=self.budget,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

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


# Alias for backward compatibility
Project = ProjectEntity


# =============================================================================
#  PROJECT REVENUE RECOGNIZER
# =============================================================================


@dataclass
class ProjectRevenueRecognizer:
    """
    Tracks recognized revenue, cost, and profit for a project.
    Uses percentage-of-completion (cost-to-cost) method.
    Immutable – every recognition produces a new instance.
    """

    project_id: UUID
    project_code: str
    total_contract_value: Decimal
    total_estimated_cost: Decimal  # sum of all planned costs (budget)
    total_actual_cost: Decimal  # incurred to date
    total_recognized_revenue: Decimal
    total_recognized_cost: Decimal
    total_recognized_profit: Decimal
    cumulative_percentage: float  # 0.0 to 100.0
    last_recognized_date: datetime | None
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.total_contract_value < 0:
            raise ValueError("Total contract value cannot be negative")
        if self.total_estimated_cost < 0:
            raise ValueError("Total estimated cost cannot be negative")
        if self.total_actual_cost < 0:
            raise ValueError("Total actual cost cannot be negative")
        if self.cumulative_percentage < 0 or self.cumulative_percentage > 100:
            raise ValueError("Cumulative percentage must be between 0 and 100")
        # Normalize timezone
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.last_recognized_date and self.last_recognized_date.tzinfo is None:
            object.__setattr__(
                self, "last_recognized_date", self.last_recognized_date.replace(tzinfo=UTC)
            )

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

    @classmethod
    def create(cls, project: ProjectEntity) -> ProjectRevenueRecognizer:
        """Factory method to create a new recognizer from a project."""
        return cls(
            project_id=project.project_id,
            project_code=project.project_code,
            total_contract_value=project.contract_value,
            total_estimated_cost=project.budget
            if project.budget > 0
            else project.contract_value * Decimal("0.7"),
            total_actual_cost=Decimal(0),
            total_recognized_revenue=Decimal(0),
            total_recognized_cost=Decimal(0),
            total_recognized_profit=Decimal(0),
            cumulative_percentage=0.0,
            last_recognized_date=None,
            version=1,
        )

    def recognize_revenue(
        self,
        project: ProjectEntity,
        cost_tracker: Any,
        as_of_date: datetime,
        recognized_by: str,
    ) -> ProjectRevenueRecognizer:
        """
        Recognize revenue up to as_of_date using cost-to-cost method.
        Requires a cost_tracker that has total_cost attribute (incurred costs).
        Returns a new recognizer instance with updated values.
        """
        if as_of_date.tzinfo is None:
            as_of_date = as_of_date.replace(tzinfo=UTC)

        current_actual_cost = (
            cost_tracker.total_cost
            if hasattr(cost_tracker, "total_cost")
            else self.total_actual_cost
        )

        if self.total_estimated_cost <= 0:
            return self

        new_percentage = min(100.0, float(current_actual_cost / self.total_estimated_cost * 100))
        new_recognized_revenue = self.total_contract_value * Decimal(str(new_percentage / 100))

        incremental_revenue = new_recognized_revenue - self.total_recognized_revenue
        if incremental_revenue < 0:
            incremental_revenue = Decimal(0)

        new_recognized_cost = current_actual_cost
        new_recognized_profit = new_recognized_revenue - new_recognized_cost

        self._record_audit(
            "revenue_recognized",
            recognized_by,
            {
                "as_of_date": as_of_date.isoformat(),
                "previous_percentage": self.cumulative_percentage,
                "new_percentage": new_percentage,
                "incremental_revenue": str(incremental_revenue),
                "total_recognized_revenue": str(new_recognized_revenue),
            },
        )

        return ProjectRevenueRecognizer(
            project_id=self.project_id,
            project_code=self.project_code,
            total_contract_value=self.total_contract_value,
            total_estimated_cost=self.total_estimated_cost,
            total_actual_cost=current_actual_cost,
            total_recognized_revenue=new_recognized_revenue,
            total_recognized_cost=new_recognized_cost,
            total_recognized_profit=new_recognized_profit,
            cumulative_percentage=new_percentage,
            last_recognized_date=as_of_date,
            version=self.version + 1,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def get_unrecognized_revenue(self) -> Decimal:
        return self.total_contract_value - self.total_recognized_revenue

    def get_unrecognized_cost(self) -> Decimal:
        return max(Decimal(0), self.total_estimated_cost - self.total_actual_cost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id),
            "project_code": self.project_code,
            "total_contract_value": str(self.total_contract_value),
            "total_estimated_cost": str(self.total_estimated_cost),
            "total_actual_cost": str(self.total_actual_cost),
            "total_recognized_revenue": str(self.total_recognized_revenue),
            "total_recognized_cost": str(self.total_recognized_cost),
            "total_recognized_profit": str(self.total_recognized_profit),
            "cumulative_percentage": self.cumulative_percentage,
            "last_recognized_date": self.last_recognized_date.isoformat()
            if self.last_recognized_date
            else None,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectRevenueRecognizer:
        return cls(
            project_id=UUID(data["project_id"]),
            project_code=data["project_code"],
            total_contract_value=Decimal(data["total_contract_value"]),
            total_estimated_cost=Decimal(data["total_estimated_cost"]),
            total_actual_cost=Decimal(data["total_actual_cost"]),
            total_recognized_revenue=Decimal(data["total_recognized_revenue"]),
            total_recognized_cost=Decimal(data["total_recognized_cost"]),
            total_recognized_profit=Decimal(data["total_recognized_profit"]),
            cumulative_percentage=data["cumulative_percentage"],
            last_recognized_date=datetime.fromisoformat(data["last_recognized_date"])
            if data.get("last_recognized_date")
            else None,
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


# =============================================================================
#  ADDITIONAL CLASSES FOR COMPATIBILITY WITH __init__.py
# =============================================================================


class RevenueMethod(Enum):
    """Method of revenue recognition."""

    PERCENTAGE_OF_COMPLETION = "percentage_of_completion"
    COMPLETED_CONTRACT = "completed_contract"
    INSTALLMENT = "installment"


class RevenueRecognitionMethod(Enum):
    """Detailed method for revenue recognition calculation."""

    COST_TO_COST = "cost_to_cost"
    EFFORTS_EXPENDED = "efforts_expended"
    UNITS_OF_DELIVERY = "units_of_delivery"


class RevenueRecognitionStatus(Enum):
    """Status of revenue recognition for a period."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class RevenueRecognitionEntry:
    """Individual revenue recognition entry for audit trail."""

    date: datetime
    amount: Decimal
    cumulative_amount: Decimal
    percentage: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "amount": str(self.amount),
            "cumulative_amount": str(self.cumulative_amount),
            "percentage": self.percentage,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RevenueRecognitionEntry:
        return cls(
            date=datetime.fromisoformat(data["date"]),
            amount=Decimal(data["amount"]),
            cumulative_amount=Decimal(data["cumulative_amount"]),
            percentage=data["percentage"],
            note=data.get("note", ""),
        )


class ProjectRevenueRecognizerRepository:
    """Repository interface for ProjectRevenueRecognizer."""

    async def get_by_project_id(
        self, project_id: UUID, legal_entity_id: UUID
    ) -> ProjectRevenueRecognizer | None:
        raise NotImplementedError

    async def save(self, recognizer: ProjectRevenueRecognizer, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, project_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# =============================================================================
#  REPOSITORY (preserved from original)
# =============================================================================


class ProjectEntityRepository:
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


# =============================================================================
#  EXPORTS
# =============================================================================

__all__ = [
    "CostType",
    "Project",
    "ProjectEntity",
    "ProjectEntityRepository",
    "ProjectRevenueRecognizer",
    "ProjectRevenueRecognizerRepository",
    "ProjectStatus",
    "ProjectType",
    "RevenueMethod",
    "RevenueRecognitionEntry",
    "RevenueRecognitionMethod",
    "RevenueRecognitionStatus",
]
