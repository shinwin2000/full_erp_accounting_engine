#!/usr/bin/env python3
"""
Module: sqlalchemy_project_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of ProjectRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.project_repository_port import ProjectRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


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
    __table_args__ = (
        Index("idx_task_project", "project_id"),
        Index("idx_task_status", "status"),
    )

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


class SQLAlchemyProjectRepository(ProjectRepositoryPort):
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def _get_session(self) -> AsyncSession:
        return self._session_factory()

    async def save_project(self, project) -> None:
        async with await self._get_session() as session, session.begin():
            stmt = select(ProjectTable).where(ProjectTable.id == project.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                # update
                existing.project_name = project.name
                existing.customer_id = project.customer_id
                existing.customer_name = project.customer_name
                existing.project_type = project.project_type.value
                existing.status = project.status.value
                existing.start_date = project.start_date
                existing.end_date = project.end_date
                existing.budget_amount = project.budget_amount
                existing.actual_cost = project.total_cost
                existing.billed_amount = project.total_billed
                existing.description = project.description
                existing.updated_at = datetime.utcnow()
            else:
                new = ProjectTable(
                    id=project.id,
                    legal_entity_id=project.legal_entity_id,
                    project_code=project.project_code,
                    project_name=project.name,
                    customer_id=project.customer_id,
                    customer_name=project.customer_name,
                    project_type=project.project_type.value,
                    status=project.status.value,
                    start_date=project.start_date,
                    end_date=project.end_date,
                    budget_amount=project.budget_amount,
                    actual_cost=project.total_cost,
                    billed_amount=project.total_billed,
                    description=project.description,
                    created_by=project.created_by,
                )
                session.add(new)

    async def get_project(self, project_id: UUID):
        async with await self._get_session() as session:
            stmt = select(ProjectTable).where(ProjectTable.id == project_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return self._to_project(row)

    async def find_by_code(self, legal_entity_id: UUID, project_code: str):
        async with await self._get_session() as session:
            stmt = select(ProjectTable).where(
                ProjectTable.legal_entity_id == legal_entity_id,
                ProjectTable.project_code == project_code,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._to_project(row) if row else None

    async def list_projects(self, legal_entity_id: UUID, status: str | None = None):
        async with await self._get_session() as session:
            stmt = select(ProjectTable).where(ProjectTable.legal_entity_id == legal_entity_id)
            if status:
                stmt = stmt.where(ProjectTable.status == status)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_project(row) for row in rows]

    async def save_time_entry(self, time_entry) -> None:
        async with await self._get_session() as session, session.begin():
            # In production, we'd have a separate table for time entries.
            # For simplicity, we'll just log; implement if needed.
            pass

    async def list_time_entries(self, project_id: UUID):
        return []

    async def save_billing(self, billing) -> None:
        async with await self._get_session() as session, session.begin():
            # Implement if needed
            pass

    async def get_last_invoice_number(self, legal_entity_id: UUID) -> str | None:
        async with await self._get_session() as session:
            stmt = (
                select(ProjectTable.project_code).order_by(ProjectTable.created_at.desc()).limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def save_retainer_contract(self, contract) -> None:
        async with await self._get_session() as session, session.begin():
            # Implement if needed
            pass

    def _to_project(self, row):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            project_code=row.project_code,
            name=row.project_name,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            project_type=row.project_type,
            status=row.status,
            start_date=row.start_date,
            end_date=row.end_date,
            budget_amount=row.budget_amount,
            total_cost=row.actual_cost,
            total_billed=row.billed_amount,
            total_recognized_revenue=row.billed_amount,  # simplified
            description=row.description,
            created_by=row.created_by,
            created_at=row.created_at,
        )


__all__ = ["ProjectTable", "SQLAlchemyProjectRepository", "TaskTable"]
