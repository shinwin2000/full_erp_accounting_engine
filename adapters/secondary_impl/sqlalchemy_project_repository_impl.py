#!/usr/bin/env python3
"""
Module: sqlalchemy_project_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of ProjectRepositoryPort.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Column, Date, DateTime, Index, Numeric, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.project_repository_port import (
    ProjectEntity,
    ProjectExpenseEntry,
    ProjectRepositoryPort,
    ProjectTaskEntity,
    ProjectTimeEntry,
)

logger = logging.getLogger(__name__)

Base = declarative_base()

# ============================================================================
# ORM MODELS
# ============================================================================

class ProjectTable(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("idx_project_legal_entity", "legal_entity_id"),
        Index("idx_project_code", "project_code", unique=True),
        Index("idx_project_customer", "customer_id"),
        Index("idx_project_status", "status"),
    )
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    project_code = Column(String(50), nullable=False, unique=True)
    project_name = Column(String(200), nullable=False)
    customer_id = Column(PGUUID(as_uuid=True), nullable=False)
    customer_name = Column(String(200), nullable=False)
    project_type = Column(String(20), nullable=False, default="FIXED_PRICE")
    status = Column(String(20), nullable=False, default="PLANNING")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    budget_amount = Column(Numeric(20, 2), nullable=False, default=0)
    actual_cost = Column(Numeric(20, 2), nullable=False, default=0)
    billed_amount = Column(Numeric(20, 2), nullable=False, default=0)
    description = Column(Text, nullable=True)
    project_manager_id = Column(PGUUID(as_uuid=True), nullable=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class TaskTable(Base):
    __tablename__ = "project_tasks"
    __table_args__ = (Index("idx_task_project", "project_id"), Index("idx_task_status", "status"))
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(PGUUID(as_uuid=True), nullable=False)
    task_code = Column(String(50), nullable=False)
    task_name = Column(String(200), nullable=False)
    planned_start_date = Column(Date, nullable=False)
    planned_end_date = Column(Date, nullable=False)
    actual_start_date = Column(Date, nullable=True)
    actual_end_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="NOT_STARTED")
    planned_hours = Column(Numeric(10, 2), nullable=False, default=0)
    actual_hours = Column(Numeric(10, 2), nullable=False, default=0)
    planned_cost = Column(Numeric(20, 2), nullable=False, default=0)
    actual_cost = Column(Numeric(20, 2), nullable=False, default=0)
    assigned_to_id = Column(PGUUID(as_uuid=True), nullable=True)
    description = Column(Text, nullable=True)


class TimeEntryTable(Base):
    __tablename__ = "project_time_entries"
    __table_args__ = (
        Index("idx_time_project", "project_id"),
        Index("idx_time_task", "task_id"),
        Index("idx_time_employee", "employee_id"),
        Index("idx_time_date", "entry_date"),
    )
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(PGUUID(as_uuid=True), nullable=False)
    task_id = Column(PGUUID(as_uuid=True), nullable=False)
    employee_id = Column(PGUUID(as_uuid=True), nullable=False)
    entry_date = Column(Date, nullable=False)
    hours = Column(Numeric(10, 2), nullable=False)
    billable = Column(String(1), nullable=False, default="Y")  # Y/N
    hourly_rate = Column(Numeric(20, 2), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class ExpenseEntryTable(Base):
    __tablename__ = "project_expense_entries"
    __table_args__ = (
        Index("idx_expense_project", "project_id"),
        Index("idx_expense_task", "task_id"),
        Index("idx_expense_date", "expense_date"),
    )
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(PGUUID(as_uuid=True), nullable=False)
    task_id = Column(PGUUID(as_uuid=True), nullable=True)
    expense_date = Column(Date, nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    expense_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    vendor_id = Column(PGUUID(as_uuid=True), nullable=True)
    billable = Column(String(1), nullable=False, default="Y")  # Y/N


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================

class SQLAlchemyProjectRepository(ProjectRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # MAPPING: ORM ↔ Domain
    # ========================================================================

    def _project_to_domain(self, row: ProjectTable) -> ProjectEntity:
        return ProjectEntity(
            id=row.id,
            project_code=row.project_code,
            project_name=row.project_name,
            legal_entity_id=row.legal_entity_id,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            project_type=row.project_type,
            status=row.status,
            start_date=row.start_date,
            end_date=row.end_date,
            budget_amount=row.budget_amount,
            actual_cost=row.actual_cost,
            billed_amount=row.billed_amount,
            description=row.description,
            project_manager_id=row.project_manager_id,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _project_to_orm(self, project: ProjectEntity) -> ProjectTable:
        return ProjectTable(
            id=project.id,
            legal_entity_id=project.legal_entity_id,
            project_code=project.project_code,
            project_name=project.project_name,
            customer_id=project.customer_id,
            customer_name=project.customer_name,
            project_type=project.project_type,
            status=project.status,
            start_date=project.start_date,
            end_date=project.end_date,
            budget_amount=project.budget_amount,
            actual_cost=project.actual_cost,
            billed_amount=project.billed_amount,
            description=project.description,
            project_manager_id=project.project_manager_id,
            created_by=project.created_by,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    def _task_to_domain(self, row: TaskTable) -> ProjectTaskEntity:
        return ProjectTaskEntity(
            id=row.id,
            project_id=row.project_id,
            task_code=row.task_code,
            task_name=row.task_name,
            planned_start_date=row.planned_start_date,
            planned_end_date=row.planned_end_date,
            actual_start_date=row.actual_start_date,
            actual_end_date=row.actual_end_date,
            status=row.status,
            planned_hours=row.planned_hours,
            actual_hours=row.actual_hours,
            planned_cost=row.planned_cost,
            actual_cost=row.actual_cost,
            assigned_to_id=row.assigned_to_id,
            description=row.description,
        )

    def _time_entry_to_domain(self, row: TimeEntryTable) -> ProjectTimeEntry:
        return ProjectTimeEntry(
            id=row.id,
            project_id=row.project_id,
            task_id=row.task_id,
            employee_id=row.employee_id,
            entry_date=row.entry_date,
            hours=row.hours,
            billable=row.billable == "Y",
            hourly_rate=row.hourly_rate,
            description=row.description,
            created_at=row.created_at,
        )

    def _expense_entry_to_domain(self, row: ExpenseEntryTable) -> ProjectExpenseEntry:
        return ProjectExpenseEntry(
            id=row.id,
            project_id=row.project_id,
            task_id=row.task_id,
            expense_date=row.expense_date,
            amount=row.amount,
            expense_type=row.expense_type,
            description=row.description,
            vendor_id=row.vendor_id,
            billable=row.billable == "Y",
        )

    # ========================================================================
    # PROJECT METHODS
    # ========================================================================

    async def save_project(self, project: ProjectEntity) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(ProjectTable).where(ProjectTable.id == project.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                # Update
                existing.project_name = project.project_name
                existing.customer_id = project.customer_id
                existing.customer_name = project.customer_name
                existing.project_type = project.project_type
                existing.status = project.status
                existing.start_date = project.start_date
                existing.end_date = project.end_date
                existing.budget_amount = project.budget_amount
                existing.actual_cost = project.actual_cost
                existing.billed_amount = project.billed_amount
                existing.description = project.description
                existing.project_manager_id = project.project_manager_id
                existing.updated_at = datetime.utcnow()
            else:
                session.add(self._project_to_orm(project))

    async def get_project_by_id(self, project_id: UUID) -> ProjectEntity | None:
        session = await self._get_session()
        stmt = select(ProjectTable).where(ProjectTable.id == project_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._project_to_domain(row) if row else None

    async def get_project_by_code(self, project_code: str, legal_entity_id: UUID) -> ProjectEntity | None:
        session = await self._get_session()
        stmt = select(ProjectTable).where(
            ProjectTable.project_code == project_code,
            ProjectTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._project_to_domain(row) if row else None

    async def list_projects_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[ProjectEntity]:
        session = await self._get_session()
        stmt = select(ProjectTable).where(ProjectTable.legal_entity_id == legal_entity_id)
        if status:
            stmt = stmt.where(ProjectTable.status == status)
        stmt = stmt.order_by(ProjectTable.project_code).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._project_to_domain(row) for row in rows]

    async def list_projects_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[ProjectEntity]:
        session = await self._get_session()
        stmt = select(ProjectTable).where(
            ProjectTable.customer_id == customer_id,
            ProjectTable.legal_entity_id == legal_entity_id,
        ).order_by(ProjectTable.project_code)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._project_to_domain(row) for row in rows]

    async def update_project_status(
        self, project_id: UUID, new_status: str, updated_by: UUID
    ) -> None:
        """
        Update project status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(ProjectTable).where(ProjectTable.id == project_id).with_for_update()
            result = await session.execute(stmt_lock)
            project = result.scalar_one_or_none()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # 2. Update the locked row
            project.status = new_status
            project.updated_at = datetime.utcnow()
            # updated_by not stored in ProjectTable, but we log
            logger.info(f"Project {project_id} status updated to {new_status} by {updated_by}")

    async def get_last_project_code(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = select(ProjectTable.project_code).where(
            ProjectTable.legal_entity_id == legal_entity_id
        ).order_by(ProjectTable.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ========================================================================
    # TASK METHODS
    # ========================================================================

    async def save_task(self, task: ProjectTaskEntity) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(TaskTable).where(TaskTable.id == task.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.task_name = task.task_name
                existing.planned_start_date = task.planned_start_date
                existing.planned_end_date = task.planned_end_date
                existing.actual_start_date = task.actual_start_date
                existing.actual_end_date = task.actual_end_date
                existing.status = task.status
                existing.planned_hours = task.planned_hours
                existing.actual_hours = task.actual_hours
                existing.planned_cost = task.planned_cost
                existing.actual_cost = task.actual_cost
                existing.assigned_to_id = task.assigned_to_id
                existing.description = task.description
            else:
                new = TaskTable(
                    id=task.id,
                    project_id=task.project_id,
                    task_code=task.task_code,
                    task_name=task.task_name,
                    planned_start_date=task.planned_start_date,
                    planned_end_date=task.planned_end_date,
                    actual_start_date=task.actual_start_date,
                    actual_end_date=task.actual_end_date,
                    status=task.status,
                    planned_hours=task.planned_hours,
                    actual_hours=task.actual_hours,
                    planned_cost=task.planned_cost,
                    actual_cost=task.actual_cost,
                    assigned_to_id=task.assigned_to_id,
                    description=task.description,
                )
                session.add(new)

    async def get_task_by_id(self, task_id: UUID) -> ProjectTaskEntity | None:
        session = await self._get_session()
        stmt = select(TaskTable).where(TaskTable.id == task_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._task_to_domain(row) if row else None

    async def list_tasks_by_project(self, project_id: UUID) -> list[ProjectTaskEntity]:
        session = await self._get_session()
        stmt = select(TaskTable).where(TaskTable.project_id == project_id).order_by(TaskTable.task_code)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._task_to_domain(row) for row in rows]

    async def update_task_status(
        self, task_id: UUID, new_status: str, updated_by: UUID
    ) -> None:
        """
        Update task status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(TaskTable).where(TaskTable.id == task_id).with_for_update()
            result = await session.execute(stmt_lock)
            task = result.scalar_one_or_none()
            if not task:
                raise ValueError(f"Task {task_id} not found")

            # 2. Update the locked row
            task.status = new_status
            logger.info(f"Task {task_id} status updated to {new_status} by {updated_by}")

    # ========================================================================
    # TIME ENTRY METHODS
    # ========================================================================

    async def save_time_entry(self, entry: ProjectTimeEntry) -> None:
        session = await self._get_session()
        table = TimeEntryTable(
            id=entry.id,
            project_id=entry.project_id,
            task_id=entry.task_id,
            employee_id=entry.employee_id,
            entry_date=entry.entry_date,
            hours=entry.hours,
            billable="Y" if entry.billable else "N",
            hourly_rate=entry.hourly_rate,
            description=entry.description,
            created_at=entry.created_at,
        )
        session.add(table)
        await session.flush()

    async def list_time_entries_by_project(
        self, project_id: UUID, from_date: date, to_date: date
    ) -> list[ProjectTimeEntry]:
        session = await self._get_session()
        stmt = select(TimeEntryTable).where(
            TimeEntryTable.project_id == project_id,
            TimeEntryTable.entry_date >= from_date,
            TimeEntryTable.entry_date <= to_date,
        ).order_by(TimeEntryTable.entry_date)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._time_entry_to_domain(row) for row in rows]

    # ========================================================================
    # EXPENSE ENTRY METHODS
    # ========================================================================

    async def save_expense_entry(self, entry: ProjectExpenseEntry) -> None:
        session = await self._get_session()
        table = ExpenseEntryTable(
            id=entry.id,
            project_id=entry.project_id,
            task_id=entry.task_id,
            expense_date=entry.expense_date,
            amount=entry.amount,
            expense_type=entry.expense_type,
            description=entry.description,
            vendor_id=entry.vendor_id,
            billable="Y" if entry.billable else "N",
        )
        session.add(table)
        await session.flush()

    async def list_expense_entries_by_project(
        self, project_id: UUID, from_date: date, to_date: date
    ) -> list[ProjectExpenseEntry]:
        session = await self._get_session()
        stmt = select(ExpenseEntryTable).where(
            ExpenseEntryTable.project_id == project_id,
            ExpenseEntryTable.expense_date >= from_date,
            ExpenseEntryTable.expense_date <= to_date,
        ).order_by(ExpenseEntryTable.expense_date)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._expense_entry_to_domain(row) for row in rows]

    # ========================================================================
    # FINANCIAL METHODS
    # ========================================================================

    async def update_project_costs(self, project_id: UUID, additional_cost: Decimal) -> None:
        """
        Update project actual cost atomically with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(ProjectTable).where(ProjectTable.id == project_id).with_for_update()
            result = await session.execute(stmt_lock)
            project = result.scalar_one_or_none()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # 2. Update the locked row atomically
            project.actual_cost += additional_cost
            project.updated_at = datetime.utcnow()

    async def update_project_billed(self, project_id: UUID, billed_amount: Decimal) -> None:
        """
        Update project billed amount atomically with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(ProjectTable).where(ProjectTable.id == project_id).with_for_update()
            result = await session.execute(stmt_lock)
            project = result.scalar_one_or_none()
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # 2. Update the locked row atomically
            project.billed_amount += billed_amount
            project.updated_at = datetime.utcnow()

    async def get_project_financial_summary(self, project_id: UUID) -> dict[str, Decimal]:
        project = await self.get_project_by_id(project_id)
        if not project:
            return {}
        return {
            "budget_amount": project.budget_amount,
            "actual_cost": project.actual_cost,
            "billed_amount": project.billed_amount,
            "remaining_budget": project.budget_amount - project.actual_cost,
        }

    # ========================================================================
    # LEGACY/INTERNAL METHODS (untuk kompatibilitas)
    # ========================================================================

    async def get_project(self, project_id: UUID) -> ProjectEntity | None:
        return await self.get_project_by_id(project_id)

    async def find_by_code(self, legal_entity_id: UUID, project_code: str) -> ProjectEntity | None:
        return await self.get_project_by_code(project_code, legal_entity_id)

    async def list_projects(self, legal_entity_id: UUID, status: str | None = None) -> list[ProjectEntity]:
        return await self.list_projects_by_legal_entity(legal_entity_id, status)


__all__ = ["ExpenseEntryTable", "ProjectTable", "SQLAlchemyProjectRepository", "TaskTable", "TimeEntryTable"]