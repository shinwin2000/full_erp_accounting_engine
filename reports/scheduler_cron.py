#!/usr/bin/env python3
"""
Module: scheduler_cron.py
Layer: Reports
Responsibility: Menjadwalkan laporan periodik (daily, weekly, monthly, quarterly, yearly)
               menggunakan cron expression atau interval. Mengintegrasikan dengan
               report generator untuk menghasilkan laporan otomatis dan mendistribusikan
               ke penerima melalui email atau cloud storage. Juga menyediakan
               manajemen job (add, remove, pause, resume) dan monitoring.
Dependencies:
- apscheduler (AsyncIOScheduler), asyncio, logging, datetime
- reports.generator_pdf_excel_html (ReportGenerator)
- reports.distributor_email_whatsapp (ReportDistributor)
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml -> DIINJEKSI DARI LUAR (tidak diimpor langsung)
Audit: Setiap job laporan yang dijalankan dicatat. Laporan yang dihasilkan
       disimpan dan distribusinya dicatat untuk audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.report_repository_port import ReportRepositoryPort
from reports.distributor_email_whatsapp import ReportDistributor, get_report_distributor

# Internal dependencies
from reports.generator_pdf_excel_html import ReportGenerator, get_report_generator

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "timezone": "Asia/Jakarta",
    "job_defaults": {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
}


class ScheduleFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


# ============================================================================
# EXCEPTIONS
# ============================================================================


class ReportSchedulerError(Exception):
    """Base exception untuk report scheduler."""

    pass


class JobNotFoundError(ReportSchedulerError):
    """Job tidak ditemukan."""

    pass


# ============================================================================
# REPORT JOB
# ============================================================================


class ReportJob:
    """
    Job untuk laporan terjadwal.
    """

    __slots__ = (
        "created_at",
        "cron_expression",
        "frequency",
        "is_active",
        "job_id",
        "last_run",
        "last_status",
        "name",
        "output_format",
        "parameters",
        "recipient_emails",
        "recipient_whatsapps",
        "recipients",
        "report_type",
        "schedule_time",
    )

    def __init__(
        self,
        job_id: str,
        name: str,
        report_type: str,
        parameters: dict,
        output_format: str,
        frequency: ScheduleFrequency,
        cron_expression: str | None = None,
        schedule_time: str | None = None,
        recipients: list[str] | None = None,
        recipient_emails: list[str] | None = None,
        recipient_whatsapps: list[str] | None = None,
        is_active: bool = True,
    ):
        self.job_id = job_id
        self.name = name
        self.report_type = report_type
        self.parameters = parameters
        self.output_format = output_format
        self.frequency = frequency
        self.cron_expression = cron_expression
        self.schedule_time = schedule_time or "00:00"
        self.recipients = recipients or []
        self.recipient_emails = recipient_emails or []
        self.recipient_whatsapps = recipient_whatsapps or []
        self.is_active = is_active
        self.created_at = datetime.now(UTC)
        self.last_run: datetime | None = None
        self.last_status: str | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "report_type": self.report_type,
            "parameters": self.parameters,
            "output_format": self.output_format,
            "frequency": (
                self.frequency.value if hasattr(self.frequency, "value") else self.frequency
            ),
            "cron_expression": self.cron_expression,
            "schedule_time": self.schedule_time,
            "recipients": self.recipients,
            "recipient_emails": self.recipient_emails,
            "recipient_whatsapps": self.recipient_whatsapps,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_status": self.last_status,
        }


# ============================================================================
# REPORT SCHEDULER
# ============================================================================


class ReportScheduler:
    """
    Scheduler untuk laporan periodik menggunakan APScheduler.

    Fitur:
    - Menjadwalkan laporan dengan cron atau interval
    - Mendukung berbagai frekuensi (daily, weekly, monthly, quarterly, yearly)
    - Integrasi dengan report generator dan distributor
    - Manajemen job (add, remove, pause, resume)
    - Job persistence ke database (opsional)
    - Monitoring job execution
    """

    def __init__(self, config: dict[str, Any] | None = None, report_repo: ReportRepositoryPort | None = None):
        self.config = self._prepare_config(config)
        self._scheduler: AsyncIOScheduler | None = None
        self._report_generator: ReportGenerator | None = None
        self._distributor: ReportDistributor | None = None
        self._jobs: dict[str, ReportJob] = {}
        self._running = False
        # `report_repo` dipakai oleh method CRUD jadwal (create_schedule/
        # list_schedules/dst di bagian bawah class ini) - lihat `_get_repo()`.
        # Opsional & lazy supaya konstruksi `ReportScheduler()` sederhana
        # (tanpa argumen) tetap jalan seperti sebelumnya (dipakai juga oleh
        # singleton module-level `get_report_scheduler()` di bawah).
        self._report_repo = report_repo

    def _prepare_config(self, config: dict | None) -> dict:
        """Siapkan konfigurasi dari parameter atau default."""
        if config is not None:
            result = DEFAULT_CONFIG.copy()
            for key, value in config.items():
                if key in result and isinstance(value, dict):
                    result[key].update(value)
                else:
                    result[key] = value
            return result
        return DEFAULT_CONFIG.copy()

    async def _get_report_generator(self) -> ReportGenerator:
        if self._report_generator is None:
            self._report_generator = await get_report_generator()
        return self._report_generator

    async def _get_distributor(self) -> ReportDistributor:
        if self._distributor is None:
            self._distributor = await get_report_distributor()
        return self._distributor

    async def start(self) -> None:
        """Start the report scheduler."""
        if self._scheduler is not None:
            logger.warning("Scheduler already running")
            return

        job_defaults = self.config.get(
            "job_defaults", {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
        )

        self._scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": AsyncIOExecutor()},
            job_defaults=job_defaults,
            timezone=self.config.get("timezone", "Asia/Jakarta"),
        )

        self._scheduler.start()
        self._running = True
        logger.info("Report scheduler started")

    async def stop(self) -> None:
        """Stop the report scheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=True)
            self._scheduler = None
            self._running = False
            logger.info("Report scheduler stopped")

    def _cron_from_frequency(self, frequency: ScheduleFrequency, schedule_time: str) -> CronTrigger:
        """
        Generate cron trigger from frequency and schedule time.

        Args:
            frequency: daily, weekly, monthly, quarterly, yearly
            schedule_time: Time in HH:MM format (24-hour)
        """
        hour, minute = map(int, schedule_time.split(":"))

        if frequency == ScheduleFrequency.DAILY:
            return CronTrigger(hour=hour, minute=minute)
        elif frequency == ScheduleFrequency.WEEKLY:
            return CronTrigger(day_of_week="mon", hour=hour, minute=minute)
        elif frequency == ScheduleFrequency.MONTHLY:
            return CronTrigger(day=1, hour=hour, minute=minute)
        elif frequency == ScheduleFrequency.QUARTERLY:
            # First day of Jan, Apr, Jul, Oct
            return CronTrigger(month="1,4,7,10", day=1, hour=hour, minute=minute)
        elif frequency == ScheduleFrequency.YEARLY:
            return CronTrigger(month=1, day=1, hour=hour, minute=minute)
        else:
            raise ValueError(f"Unsupported frequency: {frequency}")

    async def add_job(self, job: ReportJob) -> str:
        """
        Add a scheduled report job.

        Args:
            job: ReportJob instance

        Returns:
            Job ID
        """
        if not self._scheduler:
            raise ReportSchedulerError("Scheduler not started. Call start() first.")

        # Build trigger
        if job.cron_expression:
            trigger = CronTrigger.from_crontab(job.cron_expression)
        else:
            trigger = self._cron_from_frequency(job.frequency, job.schedule_time)

        # Add to APScheduler
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            args=[job],
            id=job.job_id,
            name=job.name,
            replace_existing=True,
        )

        self._jobs[job.job_id] = job
        logger.info(f"Report job added: {job.name} (id={job.job_id})")
        return job.job_id

    async def remove_job(self, job_id: str) -> None:
        """
        Remove a scheduled job.
        """
        if not self._scheduler:
            raise ReportSchedulerError("Scheduler not started.")

        if job_id not in self._jobs:
            raise JobNotFoundError(f"Job {job_id} not found")

        self._scheduler.remove_job(job_id)
        del self._jobs[job_id]
        logger.info(f"Report job removed: {job_id}")

    async def pause_job(self, job_id: str) -> None:
        """
        Pause a scheduled job.
        """
        if not self._scheduler:
            raise ReportSchedulerError("Scheduler not started.")

        if job_id not in self._jobs:
            raise JobNotFoundError(f"Job {job_id} not found")

        self._scheduler.pause_job(job_id)
        self._jobs[job_id].is_active = False
        logger.info(f"Report job paused: {job_id}")

    async def resume_job(self, job_id: str) -> None:
        """
        Resume a paused job.
        """
        if not self._scheduler:
            raise ReportSchedulerError("Scheduler not started.")

        if job_id not in self._jobs:
            raise JobNotFoundError(f"Job {job_id} not found")

        self._scheduler.resume_job(job_id)
        self._jobs[job_id].is_active = True
        logger.info(f"Report job resumed: {job_id}")

    async def run_job_now(self, job_id: str) -> None:
        """
        Run a scheduled job immediately (one-time execution).
        """
        if job_id not in self._jobs:
            raise JobNotFoundError(f"Job {job_id} not found")

        job = self._jobs[job_id]
        await self._execute_job(job)
        logger.info(f"Report job executed now: {job_id}")

    async def _execute_job(self, job: ReportJob) -> None:
        """
        Execute a report job (generate and distribute).
        """
        if not job.is_active:
            logger.info(f"Report job {job.name} is inactive, skipping")
            return

        logger.info(f"Executing report job: {job.name}")
        job.last_run = datetime.now(UTC)

        try:
            # Generate report
            report_gen = await self._get_report_generator()
            result = await report_gen.generate_report(
                report_type=job.report_type,
                data=job.parameters,
                output_format=job.output_format,
                report_id=f"{job.job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            )

            file_path = Path(result["file_path"])

            # Determine recipients
            recipients = job.recipients or []
            if job.recipient_emails:
                recipients.extend(job.recipient_emails)

            if recipients:
                # Distribute report
                distributor = await self._get_distributor()
                distribution_result = await distributor.distribute(
                    file_path=file_path,
                    file_name=result["file_name"],
                    recipients=recipients,
                    delivery_method="email",
                    subject=f"Automated Report: {job.name}",
                )
                job.last_status = distribution_result.get("status", "sent")
            else:
                # No recipients, just log
                job.last_status = "generated"

            logger.info(f"Report job {job.name} executed successfully")

        except Exception as e:
            job.last_status = "failed"
            logger.error(f"Report job {job.name} failed: {e}")
            await trigger_alert(
                title="Report Job Failed",
                message=f"Automated report job '{job.name}' failed: {e}",
                severity="warning",
                source="ReportScheduler",
            )

    async def get_job(self, job_id: str) -> ReportJob | None:
        """Get job by ID."""
        return self._jobs.get(job_id)

    async def list_jobs(self, include_inactive: bool = False) -> list[ReportJob]:
        """List all registered jobs."""
        if include_inactive:
            return list(self._jobs.values())
        return [j for j in self._jobs.values() if j.is_active]

    async def get_status(self) -> dict[str, Any]:
        """Get scheduler status."""
        return {
            "running": self._running,
            "total_jobs": len(self._jobs),
            "active_jobs": len([j for j in self._jobs.values() if j.is_active]),
            "jobs": [j.to_dict() for j in self._jobs.values()],
        }

    async def load_jobs_from_db(self) -> None:
        """
        Load saved jobs from database (for persistence after restart).
        """
        # Placeholder: would load from a JobStore table in PostgreSQL
        # For now, skip
        pass

    # ========================================================================
    # CRUD JADWAL LAPORAN (baru, 2026-08-20)
    # ------------------------------------------------------------------------
    # Method di bawah ini TIDAK terkait dengan mesin eksekusi cron APScheduler
    # di atas (add_job/remove_job/start/stop) - itu tetap dipakai untuk
    # keperluannya sendiri. Method ini khusus melayani
    # POST/GET/PUT/DELETE /api/v1/reports/schedule di fastapi_report_router.py,
    # yaitu CRUD murni terhadap konfigurasi jadwal (tabel `scheduled_report`).
    # Sebelum fix ini, method-method ini SAMA SEKALI TIDAK ADA di class ini,
    # menyebabkan setiap panggilan endpoint /schedule berujung
    # `AttributeError` (setelah lolos dari DependencyNotFoundError begitu
    # ReportScheduler didaftarkan ke IoC container).
    # ========================================================================

    def _get_repo(self):
        if self._report_repo is not None:
            return self._report_repo
        from adapters.secondary_impl.sqlalchemy_report_repository_impl import (
            SQLAlchemyReportRepository,
        )

        self._report_repo = SQLAlchemyReportRepository()
        return self._report_repo

    @staticmethod
    def _compute_next_run_at(
        frequency: str,
        schedule_time: str | None,
        day_of_week: int | None,
        day_of_month: int | None,
        from_dt: datetime | None = None,
    ) -> datetime | None:
        """Hitung perkiraan kapan jadwal berikutnya jalan. Perhitungan
        sederhana (bukan cron engine penuh) - cukup untuk ditampilkan di UI
        sebagai referensi, BUKAN dipakai sebagai sumber kebenaran eksekusi
        aktual (itu tanggung jawab add_job/APScheduler kalau/ketika
        dihubungkan ke sistem ini)."""
        now = from_dt or datetime.utcnow()
        hour, minute = 0, 0
        if schedule_time:
            try:
                hour, minute = (int(p) for p in schedule_time.split(":", 1))
            except (ValueError, TypeError):
                hour, minute = 0, 0

        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if frequency == "daily":
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate
        if frequency == "weekly":
            target_dow = day_of_week if day_of_week is not None else 0
            days_ahead = (target_dow - candidate.weekday()) % 7
            candidate += timedelta(days=days_ahead)
            if candidate <= now:
                candidate += timedelta(days=7)
            return candidate
        if frequency == "monthly":
            target_day = day_of_month or 1
            year, month = candidate.year, candidate.month
            try:
                candidate = candidate.replace(day=min(target_day, 28), month=month, year=year)
            except ValueError:
                candidate = candidate.replace(day=1)
            if candidate <= now:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                candidate = candidate.replace(year=year, month=month)
            return candidate
        if frequency in ("quarterly", "semi_annually", "yearly"):
            months_map = {"quarterly": 3, "semi_annually": 6, "yearly": 12}
            step = months_map[frequency]
            candidate = candidate.replace(day=1)
            while candidate <= now:
                new_month = candidate.month + step
                new_year = candidate.year + (new_month - 1) // 12
                new_month = ((new_month - 1) % 12) + 1
                candidate = candidate.replace(year=new_year, month=new_month)
            return candidate
        # "custom" atau frekuensi tidak dikenal - tidak ada perkiraan otomatis
        return None

    async def create_schedule(
        self,
        *,
        legal_entity_id: UUID,
        report_type: str,
        schedule_name: str,
        schedule_frequency: str,
        schedule_time: str | None,
        schedule_day_of_week: int | None,
        schedule_day_of_month: int | None,
        report_format: str,
        parameters: dict[str, Any],
        recipient_emails: list[str],
        recipient_whatsapps: list[str],
        delivery_methods: list[str],
        is_active: bool,
        notes: str | None,
        created_by: UUID,
    ):
        from infrastructure.persistence_orm.scheduled_report_table import ScheduledReportTable

        now = datetime.utcnow()
        entry = ScheduledReportTable(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            schedule_name=schedule_name,
            report_type=report_type,
            schedule_frequency=schedule_frequency,
            schedule_time=schedule_time,
            schedule_day_of_week=schedule_day_of_week,
            schedule_day_of_month=schedule_day_of_month,
            report_format=report_format,
            parameters=parameters or {},
            recipient_emails=recipient_emails or [],
            recipient_whatsapps=recipient_whatsapps or [],
            delivery_methods=delivery_methods or [],
            is_active=is_active,
            notes=notes,
            next_run_at=self._compute_next_run_at(
                schedule_frequency, schedule_time, schedule_day_of_week, schedule_day_of_month, now
            ),
            created_at=now,
            updated_at=now,
            created_by=created_by,
            version=1,
        )
        return await self._get_repo().create_scheduled_report(entry)

    async def list_schedules(
        self,
        *,
        legal_entity_id: UUID,
        is_active: bool | None = None,
        report_type: str | None = None,
    ):
        return await self._get_repo().list_scheduled_reports(
            legal_entity_id=legal_entity_id, is_active=is_active, report_type=report_type
        )

    async def get_schedule_by_id(self, schedule_id: UUID, legal_entity_id: UUID):
        return await self._get_repo().get_scheduled_report_by_id(schedule_id, legal_entity_id)

    async def export_schedules(self, *, legal_entity_id: UUID, format: str = "csv") -> bytes:
        """Export seluruh jadwal laporan (tanpa filter) ke CSV/Excel/JSON.
        Dipakai oleh tombol "Export" generik di GenericListPage
        (ui/widgets/generic_list_page.py::_export), yang selalu memanggil
        `{base_path}/export` - untuk modul "Report Terjadwal" ini berarti
        mengekspor daftar jadwal yang sedang ditampilkan."""
        import csv
        import io
        import json

        schedules = await self.list_schedules(legal_entity_id=legal_entity_id)
        headers = [
            "schedule_id", "schedule_name", "report_type", "schedule_frequency",
            "schedule_time", "report_format", "is_active", "next_run_at", "last_run_at",
        ]
        rows = [
            [
                str(s.id), s.schedule_name, s.report_type, s.schedule_frequency,
                s.schedule_time or "", s.report_format, s.is_active,
                s.next_run_at.isoformat() if s.next_run_at else "",
                s.last_run_at.isoformat() if s.last_run_at else "",
            ]
            for s in schedules
        ]

        fmt = (format or "csv").lower()
        if fmt == "json":
            payload = [dict(zip(headers, row, strict=False)) for row in rows]
            return json.dumps(payload, default=str, indent=2, ensure_ascii=False).encode("utf-8")
        if fmt in ("excel", "xlsx"):
            try:
                from openpyxl import Workbook

                wb = Workbook()
                ws = wb.active
                ws.title = "Jadwal Laporan"
                ws.append(headers)
                for row in rows:
                    ws.append(row)
                buf = io.BytesIO()
                wb.save(buf)
                return buf.getvalue()
            except ImportError:
                pass  # fallback ke CSV di bawah kalau openpyxl tidak tersedia

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        return output.getvalue().encode("utf-8-sig")

    async def update_schedule(
        self,
        *,
        schedule_id: UUID,
        legal_entity_id: UUID,
        schedule_name: str,
        report_type: str,
        schedule_frequency: str,
        schedule_time: str | None,
        schedule_day_of_week: int | None,
        schedule_day_of_month: int | None,
        report_format: str,
        parameters: dict[str, Any],
        recipient_emails: list[str],
        recipient_whatsapps: list[str],
        delivery_methods: list[str],
        is_active: bool,
        notes: str | None,
        updated_by: UUID,
    ):
        next_run_at = self._compute_next_run_at(
            schedule_frequency, schedule_time, schedule_day_of_week, schedule_day_of_month
        )
        return await self._get_repo().update_scheduled_report(
            schedule_id,
            legal_entity_id,
            schedule_name=schedule_name,
            report_type=report_type,
            schedule_frequency=schedule_frequency,
            schedule_time=schedule_time,
            schedule_day_of_week=schedule_day_of_week,
            schedule_day_of_month=schedule_day_of_month,
            report_format=report_format,
            parameters=parameters or {},
            recipient_emails=recipient_emails or [],
            recipient_whatsapps=recipient_whatsapps or [],
            delivery_methods=delivery_methods or [],
            is_active=is_active,
            notes=notes,
            next_run_at=next_run_at,
            updated_by=updated_by,
        )

    async def delete_schedule(self, schedule_id: UUID, legal_entity_id: UUID, deleted_by: UUID):
        return await self._get_repo().delete_scheduled_report(schedule_id, legal_entity_id)


# ============================================================================
# SINGLETON INSTANCE dengan injeksi konfigurasi
# ============================================================================

_report_scheduler: ReportScheduler | None = None
_scheduler_config: dict | None = None


def set_scheduler_config(config: dict) -> None:
    """Set konfigurasi untuk ReportScheduler (harus dipanggil sebelum get_report_scheduler)."""
    global _scheduler_config
    _scheduler_config = config


async def get_report_scheduler() -> ReportScheduler:
    """Get singleton instance of ReportScheduler."""
    global _report_scheduler
    if _report_scheduler is None:
        _report_scheduler = ReportScheduler(config=_scheduler_config)
        await _report_scheduler.start()
    return _report_scheduler


async def shutdown_report_scheduler() -> None:
    """Shutdown report scheduler."""
    global _report_scheduler
    if _report_scheduler:
        await _report_scheduler.stop()
        _report_scheduler = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "JobNotFoundError",
    "ReportJob",
    "ReportScheduler",
    "ReportSchedulerError",
    "ScheduleFrequency",
    "get_report_scheduler",
    "set_scheduler_config",
    "shutdown_report_scheduler",
]
