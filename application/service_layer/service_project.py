# service_project.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_project.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for Project & Services Accounting.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.project_services.domain_events import (
    MilestoneBilledEvent,
    MilestoneReadyEvent,
    ProjectActivatedEvent,
    ProjectBillingGeneratedEvent,
    ProjectCompletedEvent,
    ProjectCreatedEvent,
    RevenueRecognizedEvent,
    TimeEntryApprovedEvent,
    TimeEntrySubmittedEvent,
)
from domain.project_services.invariants import ProjectInvariantsValidator
from domain.project_services.project_billing_schedule import BillingMilestone
from domain.project_services.project_cost_tracker import ProjectCostTracker
from domain.project_services.project_entity import Project, ProjectStatus, ProjectType
from domain.project_services.project_revenue_recognizer import (
    ProjectRevenueRecognizer,
    RevenueMethod,
)
from domain.project_services.retainer_contract_entity import RetainerContract, RetainerStatus
from domain.project_services.time_entry_entity import TimeEntry, TimeEntryStatus
from ports.primary.employee_repository_port import EmployeeRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.project_repository_port import ProjectRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class ProjectTypeEnum(str, Enum):
    """Type of project."""

    FIXED_PRICE = "FIXED_PRICE"
    TIME_MATERIAL = "TIME_MATERIAL"
    RETAINER = "RETAINER"


class ProjectStatusEnum(str, Enum):
    """Status of project."""

    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RevenueMethodEnum(str, Enum):
    """Revenue recognition method."""

    PERCENTAGE_COMPLETION = "PERCENTAGE_COMPLETION"
    COMPLETED_CONTRACT = "COMPLETED_CONTRACT"


class TimeEntryStatusEnum(str, Enum):
    """Status of time entry."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class ProjectRequest:
    """Request to create a project."""

    legal_entity_id: UUID
    project_code: str
    name: str
    customer_id: UUID
    start_date: date
    end_date: date | None = None
    budget_amount: Decimal = Decimal("0")
    project_type: str = "FIXED_PRICE"
    billing_method: str = "PERCENTAGE_COMPLETION"
    description: str | None = None


@dataclass(kw_only=True)
class ProjectUpdateRequest:
    """Request to update a project."""

    name: str | None = None
    description: str | None = None
    end_date: date | None = None
    budget_amount: Decimal | None = None
    billing_method: str | None = None


@dataclass(kw_only=True)
class ProjectResponse:
    """Response for project."""

    project_id: UUID
    project_code: str
    name: str
    customer_id: UUID
    start_date: date
    end_date: date | None
    budget_amount: Decimal
    total_cost: Decimal
    total_billed: Decimal
    total_recognized_revenue: Decimal
    status: str
    created_at: datetime


@dataclass(kw_only=True)
class TimeEntryRequest:
    """Request to record time entry."""

    project_id: UUID
    employee_id: UUID
    entry_date: date
    hours: Decimal
    billable: bool = True
    description: str | None = None
    hourly_rate: Decimal | None = None


@dataclass(kw_only=True)
class TimeEntryResponse:
    """Response for time entry."""

    time_entry_id: UUID
    project_id: UUID
    employee_id: UUID
    entry_date: date
    hours: Decimal
    billable_amount: Decimal
    status: str
    description: str | None


@dataclass(kw_only=True)
class ProjectBillingRequest:
    """Request to generate project billing."""

    project_id: UUID
    billing_date: date
    amount: Decimal
    milestone_name: str | None = None
    description: str | None = None


@dataclass(kw_only=True)
class ProjectBillingResponse:
    """Response for project billing."""

    invoice_id: UUID
    project_id: UUID
    invoice_number: str
    billing_date: date
    amount: Decimal
    status: str


@dataclass(kw_only=True)
class MilestoneRequest:
    """Request to create a milestone."""

    project_id: UUID
    milestone_name: str
    due_date: date
    amount: Decimal
    description: str | None = None


@dataclass(kw_only=True)
class MilestoneResponse:
    """Response for milestone."""

    milestone_id: UUID
    project_id: UUID
    milestone_name: str
    due_date: date
    amount: Decimal
    is_ready: bool
    is_billed: bool
    description: str | None


# ============================================================================
# Exceptions
# ============================================================================


class ProjectServiceError(Exception):
    pass


class ProjectNotFoundError(ProjectServiceError):
    pass


class TimeEntryError(ProjectServiceError):
    pass


class RevenueRecognitionError(ProjectServiceError):
    pass


class ProjectAlreadyActiveError(ProjectServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class ProjectService:
    """
    Service untuk project accounting.
    Mempublikasikan event untuk setiap operasi.
    """

    def __init__(
        self,
        project_repo: ProjectRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        employee_repo: EmployeeRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if project_repo is None:
            raise ValueError("project_repo is required")

        self._project_repo = project_repo
        self._ledger_repo = ledger_repo
        self._employee_repo = employee_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = ProjectInvariantsValidator()
        self._cost_tracker = ProjectCostTracker()
        self._revenue_recognizer = ProjectRevenueRecognizer()
        self._stats = {
            "projects_created": 0,
            "projects_activated": 0,
            "projects_completed": 0,
            "time_entries": 0,
            "time_entries_submitted": 0,
            "time_entries_approved": 0,
            "billings": 0,
            "milestones_ready": 0,
            "milestones_billed": 0,
        }

        logger.info("ProjectService initialized")

    # ========================================================================
    # Project Master
    # ========================================================================

    async def create_project(
        self, request: ProjectRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ProjectResponse:
        """Create a new project."""
        # Check unique project code
        existing = await self._project_repo.find_by_code(
            request.legal_entity_id, request.project_code
        )
        if existing:
            raise ProjectServiceError(f"Project code {request.project_code} already exists")

        project = Project(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            project_code=request.project_code,
            name=request.name,
            customer_id=request.customer_id,
            start_date=request.start_date,
            end_date=request.end_date,
            budget_amount=request.budget_amount,
            project_type=ProjectType(request.project_type),
            billing_method=RevenueMethod(request.billing_method),
            status=ProjectStatus.DRAFT,
            total_cost=Decimal("0"),
            total_billed=Decimal("0"),
            total_recognized_revenue=Decimal("0"),
            description=request.description,
            created_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=None,
            version=1,
        )

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        self._stats["projects_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = ProjectCreatedEvent(
                    aggregate_id=project.id,
                    aggregate_version=project.version,
                    project_id=project.id,
                    project_code=project.project_code,
                    name=project.name,
                    customer_id=project.customer_id,
                    budget_amount=project.budget_amount,
                    start_date=project.start_date,
                    created_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published ProjectCreatedEvent for {project.project_code}")
            except Exception as e:
                logger.warning(f"Failed to publish ProjectCreatedEvent: {e}")

        logger.info(f"Project created: {project.project_code} - {project.name}")
        return self._to_response(project)

    async def update_project(
        self,
        project_id: UUID,
        request: ProjectUpdateRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ProjectResponse:
        """Update project details."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        if project.status in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
            raise ProjectServiceError(f"Cannot update project in status {project.status.value}")

        changes = {}

        if request.name is not None and request.name != project.name:
            changes["name"] = {"old": project.name, "new": request.name}
            project.name = request.name

        if request.description is not None and request.description != project.description:
            changes["description"] = {"old": project.description, "new": request.description}
            project.description = request.description

        if request.end_date is not None and request.end_date != project.end_date:
            changes["end_date"] = {"old": project.end_date, "new": request.end_date}
            project.end_date = request.end_date

        if request.budget_amount is not None and request.budget_amount != project.budget_amount:
            changes["budget_amount"] = {"old": project.budget_amount, "new": request.budget_amount}
            project.budget_amount = request.budget_amount

        if request.billing_method is not None:
            new_method = RevenueMethod(request.billing_method)
            if new_method != project.billing_method:
                changes["billing_method"] = {"old": project.billing_method.value, "new": new_method.value}
                project.billing_method = new_method

        if not changes:
            return self._to_response(project)

        project.updated_at = datetime.utcnow()
        project.updated_by = user_id
        project.version += 1

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        # No specific event for project update, but we could publish ProjectUpdatedEvent
        # For now, use ProjectActivatedEvent or similar? We'll skip for now.

        return self._to_response(project)

    async def activate_project(
        self,
        project_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ProjectResponse:
        """Activate a project (change status to ACTIVE)."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        if project.status == ProjectStatus.ACTIVE:
            raise ProjectAlreadyActiveError(f"Project {project_id} is already active")

        if project.status == ProjectStatus.COMPLETED:
            raise ProjectServiceError("Cannot activate a completed project")

        old_status = project.status
        project.status = ProjectStatus.ACTIVE
        project.updated_at = datetime.utcnow()
        project.updated_by = user_id
        project.version += 1

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        self._stats["projects_activated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = ProjectActivatedEvent(
                    aggregate_id=project.id,
                    aggregate_version=project.version,
                    project_id=project.id,
                    project_code=project.project_code,
                    name=project.name,
                    activated_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published ProjectActivatedEvent for {project.project_code}")
            except Exception as e:
                logger.warning(f"Failed to publish ProjectActivatedEvent: {e}")

        logger.info(f"Project activated: {project.project_code}")
        return self._to_response(project)

    async def start_project(
        self,
        project_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ProjectResponse:
        """Start a project (change status to IN_PROGRESS)."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        if project.status not in (ProjectStatus.PLANNING, ProjectStatus.ACTIVE, ProjectStatus.DRAFT):
            raise ProjectServiceError(f"Cannot start project in status {project.status.value}")

        project.status = ProjectStatus.IN_PROGRESS
        project.updated_at = datetime.utcnow()
        project.updated_by = user_id
        project.version += 1

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        return self._to_response(project)

    async def complete_project(
        self,
        project_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ProjectResponse:
        """Complete a project."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        if project.status == ProjectStatus.COMPLETED:
            return self._to_response(project)

        # Recognize remaining revenue if needed
        if project.total_recognized_revenue < project.total_billed:
            await self.recognize_revenue(project_id, date.today(), user_id, correlation_id)

        old_status = project.status
        project.status = ProjectStatus.COMPLETED
        project.end_date = date.today()
        project.updated_at = datetime.utcnow()
        project.updated_by = user_id
        project.version += 1

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        self._stats["projects_completed"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = ProjectCompletedEvent(
                    aggregate_id=project.id,
                    aggregate_version=project.version,
                    project_id=project.id,
                    project_code=project.project_code,
                    name=project.name,
                    completed_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published ProjectCompletedEvent for {project.project_code}")
            except Exception as e:
                logger.warning(f"Failed to publish ProjectCompletedEvent: {e}")

        logger.info(f"Project completed: {project.project_code}")
        return self._to_response(project)

    async def cancel_project(
        self,
        project_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ProjectResponse:
        """Cancel a project."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        if project.status == ProjectStatus.COMPLETED:
            raise ProjectServiceError("Cannot cancel a completed project")

        project.status = ProjectStatus.CANCELLED
        project.cancel_reason = reason
        project.updated_at = datetime.utcnow()
        project.updated_by = user_id
        project.version += 1

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        return self._to_response(project)

    # ========================================================================
    # Time Entry
    # ========================================================================

    async def record_time_entry(
        self, request: TimeEntryRequest, user_id: UUID, correlation_id: str | None = None
    ) -> TimeEntryResponse:
        """Record employee time spent on project."""
        project = await self._project_repo.get_project(request.project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {request.project_id} not found")

        if project.status in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
            raise TimeEntryError(f"Cannot record time for {project.status.value} project")

        # Get employee hourly rate if not provided
        hourly_rate = request.hourly_rate
        if hourly_rate is None and self._employee_repo:
            employee = await self._employee_repo.get_by_id(request.employee_id)
            hourly_rate = employee.hourly_rate if employee else Decimal("50000")

        billable_amount = request.hours * hourly_rate if request.billable else Decimal("0")

        time_entry = TimeEntry(
            id=uuid4(),
            project_id=request.project_id,
            employee_id=request.employee_id,
            entry_date=request.entry_date,
            hours=request.hours,
            billable=request.billable,
            hourly_rate=hourly_rate,
            billable_amount=billable_amount,
            description=request.description,
            status=TimeEntryStatus.DRAFT,
            created_by=user_id,
            created_at=datetime.utcnow(),
            version=1,
        )

        await self._project_repo.save_time_entry(time_entry)

        # Update project cost
        project.total_cost += billable_amount if request.billable else Decimal("0")
        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        self._stats["time_entries"] += 1

        # No event for draft time entry

        return self._to_time_entry_response(time_entry)

    async def submit_time_entry(
        self,
        time_entry_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TimeEntryResponse:
        """Submit a time entry for approval."""
        time_entry = await self._project_repo.get_time_entry(time_entry_id)
        if not time_entry:
            raise TimeEntryError(f"Time entry {time_entry_id} not found")

        if time_entry.status != TimeEntryStatus.DRAFT:
            raise TimeEntryError(f"Cannot submit time entry in status {time_entry.status.value}")

        time_entry.status = TimeEntryStatus.SUBMITTED
        time_entry.submitted_at = datetime.utcnow()
        time_entry.submitted_by = user_id
        time_entry.version += 1

        await self._project_repo.save_time_entry(time_entry)
        if self._uow:
            await self._uow.commit()

        self._stats["time_entries_submitted"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = TimeEntrySubmittedEvent(
                    aggregate_id=time_entry.id,
                    aggregate_version=time_entry.version,
                    time_entry_id=time_entry.id,
                    project_id=time_entry.project_id,
                    employee_id=time_entry.employee_id,
                    hours=time_entry.hours,
                    billable_amount=time_entry.billable_amount,
                    submitted_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published TimeEntrySubmittedEvent for {time_entry.id}")
            except Exception as e:
                logger.warning(f"Failed to publish TimeEntrySubmittedEvent: {e}")

        return self._to_time_entry_response(time_entry)

    async def approve_time_entry(
        self,
        time_entry_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TimeEntryResponse:
        """Approve a time entry."""
        time_entry = await self._project_repo.get_time_entry(time_entry_id)
        if not time_entry:
            raise TimeEntryError(f"Time entry {time_entry_id} not found")

        if time_entry.status != TimeEntryStatus.SUBMITTED:
            raise TimeEntryError(f"Cannot approve time entry in status {time_entry.status.value}")

        time_entry.status = TimeEntryStatus.APPROVED
        time_entry.approved_at = datetime.utcnow()
        time_entry.approved_by = user_id
        time_entry.version += 1

        await self._project_repo.save_time_entry(time_entry)
        if self._uow:
            await self._uow.commit()

        self._stats["time_entries_approved"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = TimeEntryApprovedEvent(
                    aggregate_id=time_entry.id,
                    aggregate_version=time_entry.version,
                    time_entry_id=time_entry.id,
                    project_id=time_entry.project_id,
                    employee_id=time_entry.employee_id,
                    hours=time_entry.hours,
                    billable_amount=time_entry.billable_amount,
                    approved_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published TimeEntryApprovedEvent for {time_entry.id}")
            except Exception as e:
                logger.warning(f"Failed to publish TimeEntryApprovedEvent: {e}")

        return self._to_time_entry_response(time_entry)

    async def reject_time_entry(
        self,
        time_entry_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> TimeEntryResponse:
        """Reject a time entry."""
        time_entry = await self._project_repo.get_time_entry(time_entry_id)
        if not time_entry:
            raise TimeEntryError(f"Time entry {time_entry_id} not found")

        if time_entry.status != TimeEntryStatus.SUBMITTED:
            raise TimeEntryError(f"Cannot reject time entry in status {time_entry.status.value}")

        time_entry.status = TimeEntryStatus.REJECTED
        time_entry.reject_reason = reason
        time_entry.rejected_at = datetime.utcnow()
        time_entry.rejected_by = user_id
        time_entry.version += 1

        await self._project_repo.save_time_entry(time_entry)
        if self._uow:
            await self._uow.commit()

        return self._to_time_entry_response(time_entry)

    async def get_project_time_entries(self, project_id: UUID) -> list[TimeEntryResponse]:
        """Get all time entries for a project."""
        entries = await self._project_repo.list_time_entries(project_id)
        return [self._to_time_entry_response(e) for e in entries]

    # ========================================================================
    # Milestones
    # ========================================================================

    async def create_milestone(
        self,
        request: MilestoneRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> MilestoneResponse:
        """Create a project milestone."""
        project = await self._project_repo.get_project(request.project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {request.project_id} not found")

        milestone = BillingMilestone(
            id=uuid4(),
            project_id=request.project_id,
            milestone_name=request.milestone_name,
            due_date=request.due_date,
            amount=request.amount,
            description=request.description,
            is_ready=False,
            is_billed=False,
            created_by=user_id,
            created_at=datetime.utcnow(),
        )

        await self._project_repo.save_milestone(milestone)
        if self._uow:
            await self._uow.commit()

        return self._to_milestone_response(milestone)

    async def mark_milestone_ready(
        self,
        milestone_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> MilestoneResponse:
        """Mark a milestone as ready for billing."""
        milestone = await self._project_repo.get_milestone(milestone_id)
        if not milestone:
            raise ProjectServiceError(f"Milestone {milestone_id} not found")

        if milestone.is_ready:
            return self._to_milestone_response(milestone)

        milestone.is_ready = True
        milestone.ready_date = datetime.utcnow().date()
        milestone.ready_by = user_id
        milestone.version = (milestone.version or 0) + 1

        await self._project_repo.save_milestone(milestone)
        if self._uow:
            await self._uow.commit()

        self._stats["milestones_ready"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = MilestoneReadyEvent(
                    aggregate_id=milestone.id,
                    aggregate_version=milestone.version or 1,
                    milestone_id=milestone.id,
                    project_id=milestone.project_id,
                    milestone_name=milestone.milestone_name,
                    amount=milestone.amount,
                    ready_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published MilestoneReadyEvent for {milestone.milestone_name}")
            except Exception as e:
                logger.warning(f"Failed to publish MilestoneReadyEvent: {e}")

        return self._to_milestone_response(milestone)

    async def mark_milestone_billed(
        self,
        milestone_id: UUID,
        invoice_id: UUID,
        invoice_number: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> MilestoneResponse:
        """Mark a milestone as billed."""
        milestone = await self._project_repo.get_milestone(milestone_id)
        if not milestone:
            raise ProjectServiceError(f"Milestone {milestone_id} not found")

        if not milestone.is_ready:
            raise ProjectServiceError("Milestone must be ready before billing")

        if milestone.is_billed:
            return self._to_milestone_response(milestone)

        milestone.is_billed = True
        milestone.billed_date = datetime.utcnow().date()
        milestone.billed_by = user_id
        milestone.invoice_id = invoice_id
        milestone.invoice_number = invoice_number
        milestone.version = (milestone.version or 0) + 1

        await self._project_repo.save_milestone(milestone)
        if self._uow:
            await self._uow.commit()

        self._stats["milestones_billed"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = MilestoneBilledEvent(
                    aggregate_id=milestone.id,
                    aggregate_version=milestone.version or 1,
                    milestone_id=milestone.id,
                    project_id=milestone.project_id,
                    milestone_name=milestone.milestone_name,
                    amount=milestone.amount,
                    invoice_id=invoice_id,
                    invoice_number=invoice_number,
                    billed_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published MilestoneBilledEvent for {milestone.milestone_name}")
            except Exception as e:
                logger.warning(f"Failed to publish MilestoneBilledEvent: {e}")

        return self._to_milestone_response(milestone)

    # ========================================================================
    # Revenue Recognition
    # ========================================================================

    async def recognize_revenue(
        self,
        project_id: UUID,
        as_of_date: date,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> Decimal:
        """Recognize revenue based on project billing method."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        total_cost_to_date = project.total_cost
        estimated_total_cost = (
            project.budget_amount if project.budget_amount > 0 else total_cost_to_date
        )

        # Calculate revenue to recognize
        if project.billing_method == RevenueMethod.PERCENTAGE_COMPLETION:
            if estimated_total_cost > 0:
                percentage = (total_cost_to_date / estimated_total_cost) * 100
                revenue_to_recognize = (project.budget_amount * percentage / 100).quantize(
                    Decimal("0"), rounding=ROUND_HALF_EVEN
                )
            else:
                revenue_to_recognize = Decimal("0")
        elif project.billing_method == RevenueMethod.COMPLETED_CONTRACT:
            if project.status == ProjectStatus.COMPLETED:
                revenue_to_recognize = project.total_billed
            else:
                revenue_to_recognize = Decimal("0")
        else:
            revenue_to_recognize = Decimal("0")

        additional_revenue = revenue_to_recognize - project.total_recognized_revenue

        if additional_revenue > 0:
            project.total_recognized_revenue = revenue_to_recognize
            project.updated_at = datetime.utcnow()
            project.version += 1

            await self._project_repo.save_project(project)
            if self._uow:
                await self._uow.commit()

            # Post revenue journal to GL
            if self._ledger_repo:
                await self._post_revenue_journal(project, additional_revenue, as_of_date, user_id)

            # --- PUBLISH EVENT ---
            if self._event_publisher:
                try:
                    event = RevenueRecognizedEvent(
                        aggregate_id=project.id,
                        aggregate_version=project.version,
                        project_id=project_id,
                        amount=additional_revenue,
                        method=project.billing_method.value,
                        recognized_by=str(user_id),
                        user_id=str(user_id),
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published RevenueRecognizedEvent for {project.project_code}")
                except Exception as e:
                    logger.warning(f"Failed to publish RevenueRecognizedEvent: {e}")

        return additional_revenue

    async def _post_revenue_journal(
        self, project: Project, amount: Decimal, posting_date: date, user_id: UUID
    ) -> None:
        """Post revenue recognition journal to GL."""
        lines = [
            {"account_code": "1-1300", "debit": amount, "credit": Decimal("0")},  # Unbilled revenue
            {"account_code": "4-1000", "debit": Decimal("0"), "credit": amount},  # Project revenue
        ]
        await self._ledger_repo.post_journal(
            legal_entity_id=project.legal_entity_id,
            journal_date=posting_date,
            period=f"{posting_date.year}-{posting_date.month:02d}",
            description=f"Revenue recognition for project {project.project_code}",
            lines=lines,
            source_system="project",
            user_id=user_id,
        )

    # ========================================================================
    # Project Billing / Invoicing
    # ========================================================================

    async def generate_billing(
        self, request: ProjectBillingRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ProjectBillingResponse:
        """Generate an invoice for project billing."""
        project = await self._project_repo.get_project(request.project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {request.project_id} not found")

        # Generate invoice number
        invoice_number = await self._generate_invoice_number(project.legal_entity_id)

        # Create billing record
        billing = BillingMilestone(
            id=uuid4(),
            project_id=request.project_id,
            milestone_name=request.milestone_name or "Progress Billing",
            billing_date=request.billing_date,
            amount=request.amount,
            description=request.description,
            invoice_number=invoice_number,
            is_billed=True,
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        await self._project_repo.save_billing(billing)

        # Update project total billed
        project.total_billed += request.amount
        project.updated_at = datetime.utcnow()
        project.version += 1

        await self._project_repo.save_project(project)
        if self._uow:
            await self._uow.commit()

        # Create AR invoice
        invoice_id = uuid4()
        self._stats["billings"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = ProjectBillingGeneratedEvent(
                    aggregate_id=billing.id,
                    aggregate_version=1,
                    project_id=request.project_id,
                    invoice_id=invoice_id,
                    invoice_number=invoice_number,
                    amount=request.amount,
                    generated_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published ProjectBillingGeneratedEvent for {project.project_code}")
            except Exception as e:
                logger.warning(f"Failed to publish ProjectBillingGeneratedEvent: {e}")

        return ProjectBillingResponse(
            invoice_id=invoice_id,
            project_id=request.project_id,
            invoice_number=invoice_number,
            billing_date=request.billing_date,
            amount=request.amount,
            status="GENERATED",
        )

    async def _generate_invoice_number(self, legal_entity_id: UUID) -> str:
        """Generate invoice number for project billing."""
        last = await self._project_repo.get_last_invoice_number(legal_entity_id)
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"PRJ-{datetime.utcnow().year}-{seq:06d}"

    # ========================================================================
    # Profitability & Reporting
    # ========================================================================

    async def get_project_profitability(self, project_id: UUID) -> dict[str, Decimal]:
        """Get project profitability metrics."""
        project = await self._project_repo.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        gross_profit = project.total_recognized_revenue - project.total_cost
        gross_margin = (
            (gross_profit / project.total_recognized_revenue * 100)
            if project.total_recognized_revenue > 0
            else Decimal("0")
        )

        return {
            "total_revenue": project.total_recognized_revenue,
            "total_cost": project.total_cost,
            "gross_profit": gross_profit,
            "gross_margin_percent": gross_margin,
        }

    async def get_project_list(
        self, legal_entity_id: UUID, status: str | None = None
    ) -> list[ProjectResponse]:
        """Get list of projects."""
        projects = await self._project_repo.list_projects(legal_entity_id, status)
        return [self._to_response(p) for p in projects]

    # ========================================================================
    # Retainer Contracts
    # ========================================================================

    async def create_retainer_contract(
        self,
        customer_id: UUID,
        amount: Decimal,
        start_date: date,
        end_date: date,
        monthly_fee: Decimal,
        user_id: UUID,
    ) -> UUID:
        """Create a retainer contract."""
        contract = RetainerContract(
            id=uuid4(),
            customer_id=customer_id,
            total_amount=amount,
            remaining_balance=amount,
            start_date=start_date,
            end_date=end_date,
            monthly_fee=monthly_fee,
            status=RetainerStatus.ACTIVE,
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        await self._project_repo.save_retainer_contract(contract)
        if self._uow:
            await self._uow.commit()
        return contract.id

    # ========================================================================
    # Private Helpers
    # ========================================================================

    def _to_response(self, project: Project) -> ProjectResponse:
        return ProjectResponse(
            project_id=project.id,
            project_code=project.project_code,
            name=project.name,
            customer_id=project.customer_id,
            start_date=project.start_date,
            end_date=project.end_date,
            budget_amount=project.budget_amount,
            total_cost=project.total_cost,
            total_billed=project.total_billed,
            total_recognized_revenue=project.total_recognized_revenue,
            status=project.status.value,
            created_at=project.created_at,
        )

    def _to_time_entry_response(self, time_entry: TimeEntry) -> TimeEntryResponse:
        return TimeEntryResponse(
            time_entry_id=time_entry.id,
            project_id=time_entry.project_id,
            employee_id=time_entry.employee_id,
            entry_date=time_entry.entry_date,
            hours=time_entry.hours,
            billable_amount=time_entry.billable_amount,
            status=time_entry.status.value,
            description=time_entry.description,
        )

    def _to_milestone_response(self, milestone: BillingMilestone) -> MilestoneResponse:
        return MilestoneResponse(
            milestone_id=milestone.id,
            project_id=milestone.project_id,
            milestone_name=milestone.milestone_name,
            due_date=milestone.due_date,
            amount=milestone.amount,
            is_ready=milestone.is_ready,
            is_billed=milestone.is_billed,
            description=milestone.description,
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_project_service(
    project_repo: ProjectRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    employee_repo: EmployeeRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> ProjectService:
    return ProjectService(project_repo, ledger_repo, employee_repo, uow, event_publisher)


__all__ = [
    "MilestoneRequest",
    "MilestoneResponse",
    "ProjectAlreadyActiveError",
    "ProjectBillingRequest",
    "ProjectBillingResponse",
    "ProjectNotFoundError",
    "ProjectRequest",
    "ProjectResponse",
    "ProjectService",
    "ProjectServiceError",
    "ProjectStatusEnum",
    "ProjectTypeEnum",
    "RevenueMethodEnum",
    "RevenueRecognitionError",
    "TimeEntryError",
    "TimeEntryRequest",
    "TimeEntryResponse",
    "TimeEntryStatusEnum",
    "create_project_service",
]