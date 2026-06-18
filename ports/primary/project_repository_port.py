#!/usr/bin/env python3
"""
Module: project_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for project repository operations.

Defines the contract for:
- Creating and managing projects
- Project tasks and milestones
- Project budgeting and actual costs
- Project billing and revenue recognition
- Project status tracking
- Project time and expense entries
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


class ProjectEntity:
    """Represents a project (simplified)."""

    def __init__(
        self,
        id: UUID,
        project_code: str,
        project_name: str,
        legal_entity_id: UUID,
        customer_id: UUID,
        customer_name: str,
        project_type: str,  # FIXED_PRICE, TIME_MATERIALS, COST_PLUS
        status: str,  # PLANNING, ACTIVE, ON_HOLD, COMPLETED, CANCELLED
        start_date: date,
        end_date: date | None,
        budget_amount: Decimal,
        actual_cost: Decimal = Decimal("0"),
        billed_amount: Decimal = Decimal("0"),
        description: str = "",
        project_manager_id: UUID | None = None,
        created_by: UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.id = id
        self.project_code = project_code
        self.project_name = project_name
        self.legal_entity_id = legal_entity_id
        self.customer_id = customer_id
        self.customer_name = customer_name
        self.project_type = project_type
        self.status = status
        self.start_date = start_date
        self.end_date = end_date
        self.budget_amount = budget_amount
        self.actual_cost = actual_cost
        self.billed_amount = billed_amount
        self.description = description
        self.project_manager_id = project_manager_id
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()


class ProjectTaskEntity:
    """Represents a task within a project."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        task_code: str,
        task_name: str,
        planned_start_date: date,
        planned_end_date: date,
        actual_start_date: date | None,
        actual_end_date: date | None,
        status: str,  # NOT_STARTED, IN_PROGRESS, COMPLETED, BLOCKED
        planned_hours: Decimal,
        actual_hours: Decimal = Decimal("0"),
        planned_cost: Decimal = Decimal("0"),
        actual_cost: Decimal = Decimal("0"),
        assigned_to_id: UUID | None = None,
        description: str = "",
    ):
        self.id = id
        self.project_id = project_id
        self.task_code = task_code
        self.task_name = task_name
        self.planned_start_date = planned_start_date
        self.planned_end_date = planned_end_date
        self.actual_start_date = actual_start_date
        self.actual_end_date = actual_end_date
        self.status = status
        self.planned_hours = planned_hours
        self.actual_hours = actual_hours
        self.planned_cost = planned_cost
        self.actual_cost = actual_cost
        self.assigned_to_id = assigned_to_id
        self.description = description


class ProjectTimeEntry:
    """Represents a time entry against a project task."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        task_id: UUID,
        employee_id: UUID,
        entry_date: date,
        hours: Decimal,
        billable: bool,
        hourly_rate: Decimal,
        description: str = "",
        created_at: datetime = None,
    ):
        self.id = id
        self.project_id = project_id
        self.task_id = task_id
        self.employee_id = employee_id
        self.entry_date = entry_date
        self.hours = hours
        self.billable = billable
        self.hourly_rate = hourly_rate
        self.description = description
        self.created_at = created_at or datetime.utcnow()


class ProjectExpenseEntry:
    """Represents an expense entry against a project."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        task_id: UUID | None,
        expense_date: date,
        amount: Decimal,
        expense_type: str,  # MATERIAL, TRAVEL, SUBCONTRACTOR, OTHER
        description: str,
        vendor_id: UUID | None = None,
        billable: bool = True,
    ):
        self.id = id
        self.project_id = project_id
        self.task_id = task_id
        self.expense_date = expense_date
        self.amount = amount
        self.expense_type = expense_type
        self.description = description
        self.vendor_id = vendor_id
        self.billable = billable


class ProjectRepositoryPort(abc.ABC):
    """Port for project data persistence."""

    # --------------------------------------------------------------------
    # Project Management
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_project(self, project: ProjectEntity) -> None:
        """Save or update a project."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_project_by_id(self, project_id: UUID) -> ProjectEntity | None:
        """Get project by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_project_by_code(
        self, project_code: str, legal_entity_id: UUID
    ) -> ProjectEntity | None:
        """Get project by code."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_projects_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[ProjectEntity]:
        """List projects for a legal entity."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_projects_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[ProjectEntity]:
        """List projects for a customer."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_project_status(
        self, project_id: UUID, new_status: str, updated_by: UUID
    ) -> None:
        """Update project status."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_project_code(self, legal_entity_id: UUID) -> str | None:
        """Get last used project code."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Task Management
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_task(self, task: ProjectTaskEntity) -> None:
        """Save or update a project task."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_task_by_id(self, task_id: UUID) -> ProjectTaskEntity | None:
        """Get task by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_tasks_by_project(self, project_id: UUID) -> list[ProjectTaskEntity]:
        """List all tasks for a project."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_task_status(self, task_id: UUID, new_status: str, updated_by: UUID) -> None:
        """Update task status."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Time and Expenses
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_time_entry(self, entry: ProjectTimeEntry) -> None:
        """Save a time entry."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_time_entries_by_project(
        self, project_id: UUID, from_date: date, to_date: date
    ) -> list[ProjectTimeEntry]:
        """List time entries for a project within date range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def save_expense_entry(self, entry: ProjectExpenseEntry) -> None:
        """Save an expense entry."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_expense_entries_by_project(
        self, project_id: UUID, from_date: date, to_date: date
    ) -> list[ProjectExpenseEntry]:
        """List expense entries for a project within date range."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Financials
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def update_project_costs(self, project_id: UUID, additional_cost: Decimal) -> None:
        """Increment actual cost for a project."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_project_billed(self, project_id: UUID, billed_amount: Decimal) -> None:
        """Increment billed amount for a project."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_project_financial_summary(self, project_id: UUID) -> dict[str, Decimal]:
        """Get budget, actual cost, billed amount, remaining budget, etc."""
        raise NotImplementedError


class ProjectRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def save_project(self, project: ProjectEntity) -> None: ...
    async def get_project_by_id(self, project_id: UUID) -> ProjectEntity | None: ...
    async def get_project_by_code(
        self, project_code: str, legal_entity_id: UUID
    ) -> ProjectEntity | None: ...
    async def list_projects_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[ProjectEntity]: ...
    async def list_projects_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[ProjectEntity]: ...
    async def update_project_status(
        self, project_id: UUID, new_status: str, updated_by: UUID
    ) -> None: ...
    async def get_last_project_code(self, legal_entity_id: UUID) -> str | None: ...
    async def save_task(self, task: ProjectTaskEntity) -> None: ...
    async def get_task_by_id(self, task_id: UUID) -> ProjectTaskEntity | None: ...
    async def list_tasks_by_project(self, project_id: UUID) -> list[ProjectTaskEntity]: ...
    async def update_task_status(
        self, task_id: UUID, new_status: str, updated_by: UUID
    ) -> None: ...
    async def save_time_entry(self, entry: ProjectTimeEntry) -> None: ...
    async def list_time_entries_by_project(
        self, project_id: UUID, from_date: date, to_date: date
    ) -> list[ProjectTimeEntry]: ...
    async def save_expense_entry(self, entry: ProjectExpenseEntry) -> None: ...
    async def list_expense_entries_by_project(
        self, project_id: UUID, from_date: date, to_date: date
    ) -> list[ProjectExpenseEntry]: ...
    async def update_project_costs(self, project_id: UUID, additional_cost: Decimal) -> None: ...
    async def update_project_billed(self, project_id: UUID, billed_amount: Decimal) -> None: ...
    async def get_project_financial_summary(self, project_id: UUID) -> dict[str, Decimal]: ...


__all__ = [
    "ProjectEntity",
    "ProjectExpenseEntry",
    "ProjectRepositoryPort",
    "ProjectRepositoryPortProtocol",
    "ProjectTaskEntity",
    "ProjectTimeEntry",
]
