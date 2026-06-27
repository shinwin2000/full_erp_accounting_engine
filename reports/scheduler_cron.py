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

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
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

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = self._prepare_config(config)
        self._scheduler: AsyncIOScheduler | None = None
        self._report_generator: ReportGenerator | None = None
        self._distributor: ReportDistributor | None = None
        self._jobs: dict[str, ReportJob] = {}
        self._running = False

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
