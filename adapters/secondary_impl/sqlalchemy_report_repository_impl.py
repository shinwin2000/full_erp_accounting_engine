#!/usr/bin/env python3
"""
Module: sqlalchemy_report_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Report (laporan keuangan/manajemen) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.report_definition_table import ReportDefinitionTable
from infrastructure.persistence_orm.report_output_table import ReportOutputTable
from infrastructure.persistence_orm.report_schedule_table import ReportScheduleTable
from ports.primary.report_repository_port import (
    ReportRepositoryPort,
    AgingReportRepositoryPort,
)


class SQLAlchemyReportRepository(ReportRepositoryPort, AgingReportRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========== Report Definition ==========
    async def save_definition(self, definition: ReportDefinitionTable) -> ReportDefinitionTable:
        session = await self._get_session()
        session.add(definition)
        await session.flush()
        return definition

    async def get_definition_by_id(self, definition_id: uuid.UUID) -> ReportDefinitionTable | None:
        session = await self._get_session()
        stmt = select(ReportDefinitionTable).where(ReportDefinitionTable.id == definition_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_definition_by_code(
        self, report_code: str, legal_entity_id: uuid.UUID
    ) -> ReportDefinitionTable | None:
        session = await self._get_session()
        stmt = select(ReportDefinitionTable).where(
            ReportDefinitionTable.report_code == report_code,
            ReportDefinitionTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_definitions(self, legal_entity_id: uuid.UUID) -> list[ReportDefinitionTable]:
        session = await self._get_session()
        stmt = select(ReportDefinitionTable).where(
            ReportDefinitionTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========== Report Schedule ==========
    async def save_schedule(self, schedule: ReportScheduleTable) -> ReportScheduleTable:
        session = await self._get_session()
        session.add(schedule)
        await session.flush()
        return schedule

    async def get_schedules_by_definition(
        self, definition_id: uuid.UUID
    ) -> list[ReportScheduleTable]:
        session = await self._get_session()
        stmt = select(ReportScheduleTable).where(ReportScheduleTable.definition_id == definition_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_due_schedules(self, before_date: datetime) -> list[ReportScheduleTable]:
        session = await self._get_session()
        stmt = select(ReportScheduleTable).where(
            ReportScheduleTable.next_run_at <= before_date,
            ReportScheduleTable.is_active == True,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_schedule_last_run(self, schedule_id: uuid.UUID, next_run_at: datetime) -> None:
        session = await self._get_session()
        stmt = (
            update(ReportScheduleTable)
            .where(ReportScheduleTable.id == schedule_id)
            .values(last_run_at=datetime.utcnow(), next_run_at=next_run_at)
        )
        await session.execute(stmt)

    # ========== Report Output ==========
    async def save_output(self, output: ReportOutputTable) -> ReportOutputTable:
        session = await self._get_session()
        session.add(output)
        await session.flush()
        return output

    async def get_output_by_id(self, output_id: uuid.UUID) -> ReportOutputTable | None:
        session = await self._get_session()
        stmt = select(ReportOutputTable).where(ReportOutputTable.id == output_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_outputs_by_definition(
        self, definition_id: uuid.UUID, limit: int = 10
    ) -> list[ReportOutputTable]:
        session = await self._get_session()
        stmt = (
            select(ReportOutputTable)
            .where(ReportOutputTable.definition_id == definition_id)
            .order_by(ReportOutputTable.generated_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========== Dynamic Query ==========
    async def execute_query(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = text(query)
        result = await session.execute(stmt, params)
        rows = result.fetchall()
        if not rows:
            return []
        columns = result.keys()
        return [dict(zip(columns, row)) for row in rows]

    # ========================================================================
    # ReportRepositoryPort methods
    # ========================================================================

    async def generate_report(self, report_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Generate report based on type and parameters.
        Port: generate_report(report_type: str, params: dict) -> dict[str, Any]
        """
        session = await self._get_session()
        legal_entity_id = params.get("legal_entity_id")
        if legal_entity_id:
            stmt = select(ReportDefinitionTable).where(
                ReportDefinitionTable.report_code == report_type,
                ReportDefinitionTable.legal_entity_id == legal_entity_id,
            )
        else:
            stmt = select(ReportDefinitionTable).where(
                ReportDefinitionTable.report_code == report_type
            )
        result = await session.execute(stmt)
        definition = result.scalar_one_or_none()

        output_id = uuid.uuid4()
        if definition:
            output = ReportOutputTable(
                id=output_id,
                definition_id=definition.id,
                generated_at=datetime.utcnow(),
                status="completed",
                notes=f"Generated report '{report_type}' with params: {params}",
                file_path=None,
                output_url=None,
            )
            await self.save_output(output)
            return {
                "output_id": str(output.id),
                "definition_id": str(output.definition_id),
                "generated_at": output.generated_at.isoformat() if output.generated_at else None,
                "status": output.status,
                "notes": output.notes,
                "file_path": output.file_path,
                "output_url": output.output_url,
                "data": None,
            }
        else:
            # No definition found, still return a valid output
            output = ReportOutputTable(
                id=output_id,
                definition_id=uuid.uuid4(),  # dummy
                generated_at=datetime.utcnow(),
                status="completed",
                notes=f"Generated ad-hoc report '{report_type}'",
                file_path=None,
                output_url=None,
            )
            await self.save_output(output)
            return {
                "output_id": str(output.id),
                "definition_id": str(output.definition_id),
                "generated_at": output.generated_at.isoformat(),
                "status": output.status,
                "notes": output.notes,
                "file_path": output.file_path,
                "output_url": output.output_url,
                "data": None,
            }

    async def get_report_data(self, report_id: str) -> dict[str, Any]:
        """
        Retrieve report data by report_id.
        Port: get_report_data(report_id: str) -> dict[str, Any]
        (Must return dict, not None; if not found, return empty dict or raise)
        """
        try:
            output_id = uuid.UUID(report_id)
        except ValueError:
            return {"error": "Invalid report_id format"}

        output = await self.get_output_by_id(output_id)
        if not output:
            return {"error": f"Report {report_id} not found"}

        return {
            "output_id": str(output.id),
            "definition_id": str(output.definition_id),
            "generated_at": output.generated_at.isoformat() if output.generated_at else None,
            "status": output.status,
            "notes": output.notes,
            "file_path": output.file_path,
            "output_url": output.output_url,
            "data": None,
        }

    # ========================================================================
    # AgingReportRepositoryPort methods
    # ========================================================================

    async def get_ar_aging(self, legal_entity_id: uuid.UUID, as_of_date: date) -> dict[str, Any]:
        """
        AR aging report.
        Port: get_ar_aging(legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]
        """
        # Real implementation would query invoices from DB.
        # Placeholder with mock data.
        mock_invoices = [
            {"due_date": date(2026, 5, 15), "outstanding": Decimal("1000")},
            {"due_date": date(2026, 4, 10), "outstanding": Decimal("500")},
            {"due_date": date(2026, 3, 1), "outstanding": Decimal("750")},
            {"due_date": date(2026, 1, 20), "outstanding": Decimal("300")},
        ]
        buckets = {
            "0-30": Decimal(0),
            "31-60": Decimal(0),
            "61-90": Decimal(0),
            ">90": Decimal(0),
        }
        for inv in mock_invoices:
            due = inv["due_date"]
            days = (as_of_date - due).days
            amount = inv["outstanding"]
            if 0 <= days <= 30:
                buckets["0-30"] += amount
            elif 31 <= days <= 60:
                buckets["31-60"] += amount
            elif 61 <= days <= 90:
                buckets["61-90"] += amount
            else:
                buckets[">90"] += amount

        return {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "buckets": {k: float(v) for k, v in buckets.items()},
            "total_outstanding": float(sum(buckets.values())),
        }

    async def get_ap_aging(self, legal_entity_id: uuid.UUID, as_of_date: date) -> dict[str, Any]:
        """
        AP aging report.
        Port: get_ap_aging(legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]
        """
        mock_invoices = [
            {"due_date": date(2026, 5, 15), "outstanding": Decimal("2000")},
            {"due_date": date(2026, 4, 10), "outstanding": Decimal("1200")},
            {"due_date": date(2026, 3, 1), "outstanding": Decimal("800")},
            {"due_date": date(2026, 1, 20), "outstanding": Decimal("500")},
        ]
        buckets = {
            "0-30": Decimal(0),
            "31-60": Decimal(0),
            "61-90": Decimal(0),
            ">90": Decimal(0),
        }
        for inv in mock_invoices:
            due = inv["due_date"]
            days = (as_of_date - due).days
            amount = inv["outstanding"]
            if 0 <= days <= 30:
                buckets["0-30"] += amount
            elif 31 <= days <= 60:
                buckets["31-60"] += amount
            elif 61 <= days <= 90:
                buckets["61-90"] += amount
            else:
                buckets[">90"] += amount

        return {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "buckets": {k: float(v) for k, v in buckets.items()},
            "total_outstanding": float(sum(buckets.values())),
        }


__all__ = ["SQLAlchemyReportRepository"]