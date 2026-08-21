#!/usr/bin/env python3
"""
Module: sqlalchemy_report_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Report (laporan keuangan/manajemen) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.generated_report_table import GeneratedReportTable
from infrastructure.persistence_orm.report_definition_table import ReportDefinitionTable
from infrastructure.persistence_orm.report_output_table import ReportOutputTable
from infrastructure.persistence_orm.report_schedule_table import ReportScheduleTable
from infrastructure.persistence_orm.scheduled_report_table import ScheduledReportTable
from ports.primary.report_repository_port import (
    AgingReportRepositoryPort,
    ReportRepositoryPort,
)


class SQLAlchemyReportRepository(ReportRepositoryPort, AgingReportRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        # Lihat catatan panjang di sqlalchemy_umkm_repository_impl.py
        # (`_session_scope`) untuk alasan lengkap kenapa pola cache-session-
        # di-`self` (dipakai sebelum fix 2026-08-18) berbahaya untuk
        # repository yang didaftarkan sebagai singleton di IoC container
        # (ReportRepositoryPort/AgingReportRepositoryPort keduanya
        # ter-registrasi singleton - lihat AdapterRegistry log:
        # "Registered ReportRepositoryPort → SQLAlchemyReportRepository
        # (auto matching)"). `session` di sini hanya untuk caller yang
        # sengaja mengelola siklus hidup session sendiri.
        self._injected_session = session

    @asynccontextmanager
    async def _session_scope(self):
        if self._injected_session is not None:
            yield self._injected_session
            return

        from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct

        session = await get_async_session_direct()
        try:
            yield session
        finally:
            await session.close()

    # ========== Report Definition ==========
    async def save_definition(self, definition: ReportDefinitionTable) -> ReportDefinitionTable:
        async with self._session_scope() as session:
            session.add(definition)
            await session.flush()
            await session.commit()
            await session.refresh(definition)
            return definition

    async def get_definition_by_id(self, definition_id: uuid.UUID) -> ReportDefinitionTable | None:
        async with self._session_scope() as session:
            stmt = select(ReportDefinitionTable).where(ReportDefinitionTable.id == definition_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_definition_by_code(
        self, report_code: str, legal_entity_id: uuid.UUID
    ) -> ReportDefinitionTable | None:
        async with self._session_scope() as session:
            stmt = select(ReportDefinitionTable).where(
                ReportDefinitionTable.report_code == report_code,
                ReportDefinitionTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_all_definitions(self, legal_entity_id: uuid.UUID) -> list[ReportDefinitionTable]:
        async with self._session_scope() as session:
            stmt = select(ReportDefinitionTable).where(
                ReportDefinitionTable.legal_entity_id == legal_entity_id
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ========== Report Schedule ==========
    async def save_schedule(self, schedule: ReportScheduleTable) -> ReportScheduleTable:
        async with self._session_scope() as session:
            session.add(schedule)
            await session.flush()
            await session.commit()
            await session.refresh(schedule)
            return schedule

    async def get_schedules_by_definition(
        self, definition_id: uuid.UUID
    ) -> list[ReportScheduleTable]:
        async with self._session_scope() as session:
            stmt = select(ReportScheduleTable).where(ReportScheduleTable.definition_id == definition_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_due_schedules(self, before_date: datetime) -> list[ReportScheduleTable]:
        async with self._session_scope() as session:
            stmt = select(ReportScheduleTable).where(
                ReportScheduleTable.next_run_at <= before_date,
                ReportScheduleTable.is_active == True,
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_schedule_last_run(self, schedule_id: uuid.UUID, next_run_at: datetime) -> None:
        """
        Update schedule last run and next run with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        async with self._session_scope() as session:
            async with session.begin():
                stmt_lock = select(ReportScheduleTable).where(
                    ReportScheduleTable.id == schedule_id
                ).with_for_update()
                result = await session.execute(stmt_lock)
                schedule = result.scalar_one_or_none()
                if not schedule:
                    raise ValueError(f"Schedule {schedule_id} not found")

                schedule.last_run_at = datetime.utcnow()
                schedule.next_run_at = next_run_at
                await session.flush()
            # `session.begin()` sudah commit otomatis saat blok selesai
            # tanpa exception.

    # ========== Report Output ==========
    async def save_output(self, output: ReportOutputTable) -> ReportOutputTable:
        async with self._session_scope() as session:
            session.add(output)
            await session.flush()
            await session.commit()
            await session.refresh(output)
            return output

    async def get_output_by_id(self, output_id: uuid.UUID) -> ReportOutputTable | None:
        async with self._session_scope() as session:
            stmt = select(ReportOutputTable).where(ReportOutputTable.id == output_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_outputs_by_definition(
        self, definition_id: uuid.UUID, limit: int = 10
    ) -> list[ReportOutputTable]:
        async with self._session_scope() as session:
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
        async with self._session_scope() as session:
            stmt = text(query)
            result = await session.execute(stmt, params)
            rows = result.fetchall()
            if not rows:
                return []
            columns = result.keys()
            return [dict(zip(columns, row, strict=False)) for row in rows]

    # ========================================================================
    # ReportRepositoryPort methods (legacy - sistem definition/output lama)
    # ========================================================================

    async def generate_report(self, report_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Generate report based on type and parameters.
        Port: generate_report(report_type: str, params: dict) -> dict[str, Any]
        """
        async with self._session_scope() as session:
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
            output = ReportOutputTable(
                id=output_id,
                definition_id=definition.id if definition else uuid.uuid4(),
                generated_at=datetime.utcnow(),
                status="completed",
                notes=f"Generated report '{report_type}' with params: {params}",
                file_path=None,
                output_url=None,
            )
            session.add(output)
            await session.flush()
            await session.commit()
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
    # CATATAN (audit 2026-08-18): kedua method di bawah ini masih memakai
    # data MOCK/hardcoded (bukan query nyata ke database) sejak awal ditulis.
    # ReportService TIDAK memakai method ini untuk generate_ar_aging/
    # generate_ap_aging - service memanggil langsung ARService.
    # get_aging_all_customers()/APService.get_aging_all_vendors() yang
    # sudah nyata dan terbukti jalan (dipakai juga oleh endpoint
    # /api/v1/ap/ap/aging yang sudah 200 OK di produksi). Dua method di
    # bawah dibiarkan apa adanya untuk kompatibilitas port
    # (AgingReportRepositoryPort mewajibkan implementasinya), TIDAK
    # dipanggil dari jalur generate report manapun.

    async def get_ar_aging(self, legal_entity_id: uuid.UUID, as_of_date: date) -> dict[str, Any]:
        """[BELUM DIPAKAI - lihat catatan di atas] AR aging dengan data mock."""
        mock_invoices = [
            {"due_date": date(2026, 5, 15), "outstanding": Decimal("1000")},
            {"due_date": date(2026, 4, 10), "outstanding": Decimal("500")},
            {"due_date": date(2026, 3, 1), "outstanding": Decimal("750")},
            {"due_date": date(2026, 1, 20), "outstanding": Decimal("300")},
        ]
        buckets = {"0-30": Decimal(0), "31-60": Decimal(0), "61-90": Decimal(0), ">90": Decimal(0)}
        for inv in mock_invoices:
            days = (as_of_date - inv["due_date"]).days
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
        """[BELUM DIPAKAI - lihat catatan di atas] AP aging dengan data mock."""
        mock_invoices = [
            {"due_date": date(2026, 5, 15), "outstanding": Decimal("2000")},
            {"due_date": date(2026, 4, 10), "outstanding": Decimal("1200")},
            {"due_date": date(2026, 3, 1), "outstanding": Decimal("800")},
            {"due_date": date(2026, 1, 20), "outstanding": Decimal("500")},
        ]
        buckets = {"0-30": Decimal(0), "31-60": Decimal(0), "61-90": Decimal(0), ">90": Decimal(0)}
        for inv in mock_invoices:
            days = (as_of_date - inv["due_date"]).days
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

    # ========================================================================
    # GENERATED REPORT (baru, 2026-08-18) - dipakai ReportService untuk
    # list/get/status/history/delete report hasil generate_* di
    # fastapi_report_router.py.
    # ========================================================================

    async def create_generated_report(self, report: GeneratedReportTable) -> GeneratedReportTable:
        async with self._session_scope() as session:
            session.add(report)
            await session.flush()
            await session.commit()
            await session.refresh(report)
            return report

    async def get_generated_report_by_id(
        self, report_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> GeneratedReportTable | None:
        async with self._session_scope() as session:
            stmt = select(GeneratedReportTable).where(
                GeneratedReportTable.id == report_id,
                GeneratedReportTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_generated_reports(
        self,
        legal_entity_id: uuid.UUID,
        report_type: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[GeneratedReportTable], int]:
        async with self._session_scope() as session:
            conditions = [
                GeneratedReportTable.legal_entity_id == legal_entity_id,
                GeneratedReportTable.is_deleted == False,  # noqa: E712
            ]
            if report_type:
                conditions.append(GeneratedReportTable.report_type == report_type)
            if status:
                conditions.append(GeneratedReportTable.status == status)
            if start_date:
                conditions.append(GeneratedReportTable.generated_at >= start_date)
            if end_date:
                conditions.append(GeneratedReportTable.generated_at <= end_date)

            count_stmt = select(func.count()).select_from(GeneratedReportTable).where(*conditions)
            total = (await session.execute(count_stmt)).scalar() or 0

            stmt = (
                select(GeneratedReportTable)
                .where(*conditions)
                .order_by(GeneratedReportTable.generated_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all()), total

    async def soft_delete_generated_report(
        self, report_id: uuid.UUID, legal_entity_id: uuid.UUID, deleted_by: uuid.UUID
    ) -> GeneratedReportTable | None:
        async with self._session_scope() as session:
            stmt = select(GeneratedReportTable).where(
                GeneratedReportTable.id == report_id,
                GeneratedReportTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()
            if not report:
                return None
            report.is_deleted = True
            report.deleted_at = datetime.utcnow()
            report.deleted_by = deleted_by
            await session.flush()
            await session.commit()
            await session.refresh(report)
            return report

    async def update_generated_report(
        self, report_id: uuid.UUID, legal_entity_id: uuid.UUID, **fields
    ) -> GeneratedReportTable | None:
        async with self._session_scope() as session:
            stmt = select(GeneratedReportTable).where(
                GeneratedReportTable.id == report_id,
                GeneratedReportTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()
            if not report:
                return None
            for key, value in fields.items():
                if hasattr(report, key):
                    setattr(report, key, value)
            await session.flush()
            await session.commit()
            await session.refresh(report)
            return report

    # ========================================================================
    # SCHEDULED REPORT (baru, 2026-08-20) - dipakai ReportScheduler untuk
    # create/list/get/update/delete jadwal laporan di
    # POST/GET/PUT/DELETE /api/v1/reports/schedule.
    # ========================================================================

    async def create_scheduled_report(self, entry: ScheduledReportTable) -> ScheduledReportTable:
        async with self._session_scope() as session:
            session.add(entry)
            await session.flush()
            await session.commit()
            await session.refresh(entry)
            return entry

    async def get_scheduled_report_by_id(
        self, schedule_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> ScheduledReportTable | None:
        async with self._session_scope() as session:
            stmt = select(ScheduledReportTable).where(
                ScheduledReportTable.id == schedule_id,
                ScheduledReportTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_scheduled_reports(
        self,
        legal_entity_id: uuid.UUID,
        is_active: bool | None = None,
        report_type: str | None = None,
    ) -> list[ScheduledReportTable]:
        async with self._session_scope() as session:
            conditions = [ScheduledReportTable.legal_entity_id == legal_entity_id]
            if is_active is not None:
                conditions.append(ScheduledReportTable.is_active == is_active)
            if report_type:
                conditions.append(ScheduledReportTable.report_type == report_type)
            stmt = (
                select(ScheduledReportTable)
                .where(*conditions)
                .order_by(ScheduledReportTable.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_scheduled_report(
        self, schedule_id: uuid.UUID, legal_entity_id: uuid.UUID, **fields
    ) -> ScheduledReportTable | None:
        async with self._session_scope() as session:
            stmt = select(ScheduledReportTable).where(
                ScheduledReportTable.id == schedule_id,
                ScheduledReportTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            entry = result.scalar_one_or_none()
            if not entry:
                return None
            for key, value in fields.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            entry.updated_at = datetime.utcnow()
            entry.version = (entry.version or 1) + 1
            await session.flush()
            await session.commit()
            await session.refresh(entry)
            return entry

    async def delete_scheduled_report(
        self, schedule_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> ScheduledReportTable | None:
        async with self._session_scope() as session:
            stmt = select(ScheduledReportTable).where(
                ScheduledReportTable.id == schedule_id,
                ScheduledReportTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            entry = result.scalar_one_or_none()
            if not entry:
                return None
            await session.delete(entry)
            await session.commit()
            return entry


__all__ = ["SQLAlchemyReportRepository"]
