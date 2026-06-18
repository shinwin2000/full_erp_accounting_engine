#!/usr/bin/env python3
"""
Module: sqlalchemy_report_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Report (laporan keuangan/manajemen) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.report_definition_table import ReportDefinitionTable
from infrastructure.persistence_orm.report_output_table import ReportOutputTable
from infrastructure.persistence_orm.report_schedule_table import ReportScheduleTable
from ports.primary.report_repository_port import ReportRepositoryPort


class SQLAlchemyReportRepository(ReportRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== Report Definition ==========
    async def save_definition(self, definition: ReportDefinitionTable) -> ReportDefinitionTable:
        self._session.add(definition)
        await self._session.flush()
        return definition

    async def get_definition_by_id(self, definition_id: uuid.UUID) -> ReportDefinitionTable | None:
        stmt = select(ReportDefinitionTable).where(ReportDefinitionTable.id == definition_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_definition_by_code(
        self, report_code: str, legal_entity_id: uuid.UUID
    ) -> ReportDefinitionTable | None:
        stmt = select(ReportDefinitionTable).where(
            ReportDefinitionTable.report_code == report_code,
            ReportDefinitionTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_definitions(self, legal_entity_id: uuid.UUID) -> list[ReportDefinitionTable]:
        stmt = select(ReportDefinitionTable).where(
            ReportDefinitionTable.legal_entity_id == legal_entity_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ========== Report Schedule ==========
    async def save_schedule(self, schedule: ReportScheduleTable) -> ReportScheduleTable:
        self._session.add(schedule)
        await self._session.flush()
        return schedule

    async def get_schedules_by_definition(
        self, definition_id: uuid.UUID
    ) -> list[ReportScheduleTable]:
        stmt = select(ReportScheduleTable).where(ReportScheduleTable.definition_id == definition_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_due_schedules(self, before_date: datetime) -> list[ReportScheduleTable]:
        stmt = select(ReportScheduleTable).where(
            ReportScheduleTable.next_run_at <= before_date,
            ReportScheduleTable.is_active == True,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_schedule_last_run(self, schedule_id: uuid.UUID, next_run_at: datetime) -> None:
        stmt = (
            update(ReportScheduleTable)
            .where(ReportScheduleTable.id == schedule_id)
            .values(last_run_at=datetime.utcnow(), next_run_at=next_run_at)
        )
        await self._session.execute(stmt)

    # ========== Report Output ==========
    async def save_output(self, output: ReportOutputTable) -> ReportOutputTable:
        self._session.add(output)
        await self._session.flush()
        return output

    async def get_output_by_id(self, output_id: uuid.UUID) -> ReportOutputTable | None:
        stmt = select(ReportOutputTable).where(ReportOutputTable.id == output_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_outputs_by_definition(
        self, definition_id: uuid.UUID, limit: int = 10
    ) -> list[ReportOutputTable]:
        stmt = (
            select(ReportOutputTable)
            .where(ReportOutputTable.definition_id == definition_id)
            .order_by(ReportOutputTable.generated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ========== Dynamic Query ==========
    async def execute_query(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute raw SQL query for reporting (read-only)."""
        stmt = text(query)
        result = await self._session.execute(stmt, params)
        rows = result.fetchall()
        if not rows:
            return []
        columns = result.keys()
        return [dict(zip(columns, row)) for row in rows]


__all__ = ["SQLAlchemyReportRepository"]
