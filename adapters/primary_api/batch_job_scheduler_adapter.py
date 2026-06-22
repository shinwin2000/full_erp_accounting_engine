#!/usr/bin/env python3
"""
Module: batch_job_scheduler_adapter.py
Layer: Adapters (Primary API - Batch Job Scheduler)
Responsibility: Menjadwalkan dan mengeksekusi job batch periodik seperti period closing,
               depreciation run, payment run, tax filing, report generation,
               dan integrity check. Menggunakan cron schedule (APScheduler) dan
               Redis untuk distributed locking agar job tidak dijalankan duplikat
               di environment multi-instance.
Dependencies:
- apscheduler
- redis (for distributed lock)
- application.commands_cqrs (CommandBusUnified)
- infrastructure.caching.redis_manager
- kernel.sealed_gate
Audit: Setiap eksekusi batch job dicatat, termasuk start time, end time, status,
       dan output summary.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from adapters.primary_api.common.fastapi_request_id_middleware import set_request_id_for_task

# Internal dependencies - import dari package yang memiliki alias
from application.commands_cqrs import CommandBusUnified
from infrastructure.caching.redis_manager import get_redis_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

JOB_STORE_REDIS_PREFIX = "batch_job_store"
JOB_LOCK_PREFIX = "batch_lock"


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================================
# JOB DEFINITIONS
# ============================================================================


class BatchJob:
    """Base class untuk job batch."""

    def __init__(
        self,
        job_id: str,
        name: str,
        command_type: str,
        cron_expression: str,
        params: dict[str, Any],
        legal_entity_id: UUID,
        timeout_minutes: int = 30,
    ):
        self.job_id = job_id
        self.name = name
        self.command_type = command_type
        self.cron_expression = cron_expression
        self.params = params
        self.legal_entity_id = legal_entity_id
        self.timeout_minutes = timeout_minutes
        self.is_active = True
        self.last_run: datetime | None = None
        self.last_status: str | None = None
        self.last_output: str | None = None


class BatchJobScheduler:
    """
    Scheduler untuk batch job.
    """

    def __init__(self):
        self.scheduler: AsyncIOScheduler | None = None
        self.command_bus = CommandBusUnified()
        self.redis = None
        self._jobs_registry: dict[str, BatchJob] = {}
        self._running = False

    async def initialize(self):
        """Initialize scheduler with Redis job store and async executor."""
        # Get Redis client
        self.redis = await get_redis_client()

        # Configure job store with Redis
        jobstores = {
            "default": RedisJobStore(
                jobs_key=f"{JOB_STORE_REDIS_PREFIX}:jobs",
                run_times_key=f"{JOB_STORE_REDIS_PREFIX}:run_times",
                client=self.redis,
            )
        }
        executors = {"default": AsyncIOExecutor()}
        job_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="Asia/Jakarta",
        )

        # Add event listeners
        self.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)

        self.scheduler.start()
        self._running = True
        logger.info("Batch job scheduler initialized")

    async def shutdown(self):
        """Shutdown scheduler gracefully."""
        if self.scheduler:
            self.scheduler.shutdown(wait=True)
            self._running = False
            logger.info("Batch job scheduler shutdown")

    def _get_lock_key(self, job_id: str) -> str:
        return f"{JOB_LOCK_PREFIX}:{job_id}"

    async def _acquire_lock(self, job_id: str, timeout_seconds: int = 60) -> bool:
        """Acquire distributed lock for job execution."""
        lock_key = self._get_lock_key(job_id)
        # SET NX EX
        result = await self.redis.set(lock_key, str(uuid4()), nx=True, ex=timeout_seconds)
        return result is not None

    async def _release_lock(self, job_id: str):
        lock_key = self._get_lock_key(job_id)
        await self.redis.delete(lock_key)

    async def _execute_job(self, job: BatchJob):
        """Execute a batch job with distributed lock and audit."""
        request_id = f"batch-{job.job_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        set_request_id_for_task(request_id)

        # Acquire lock to prevent duplicate execution across instances
        lock_acquired = await self._acquire_lock(
            job.job_id, timeout_seconds=job.timeout_minutes * 60
        )
        if not lock_acquired:
            logger.warning(f"Job {job.job_id} already running in another instance, skipping")
            return

        try:
            logger.info(f"Starting batch job: {job.name} ({job.job_id})")
            start_time = datetime.now(UTC)
            job.last_run = start_time
            job.last_status = JobStatus.RUNNING

            # Construct command
            command = {
                "type": job.command_type,
                "data": {
                    **job.params,
                    "legal_entity_id": job.legal_entity_id,
                    "run_by": UUID("00000000-0000-0000-0000-000000000000"),  # system
                },
            }

            # Execute via command bus
            result = await self.command_bus.dispatch(command)

            end_time = datetime.now(UTC)
            duration = (end_time - start_time).total_seconds()

            success = result.get("success", True)
            job.last_status = JobStatus.SUCCESS if success else JobStatus.FAILED
            job.last_output = result.get("message", str(result))

            logger.info(f"Job {job.job_id} completed in {duration:.2f}s, status: {job.last_status}")

            # Save job execution history to audit store
            await self._save_job_history(job, start_time, end_time, success, result)

        except Exception as e:
            logger.exception(f"Job {job.job_id} failed: {e}")
            job.last_status = JobStatus.FAILED
            job.last_output = str(e)
            await self._save_job_history(
                job, start_time, datetime.now(UTC), False, {"error": str(e)}
            )
        finally:
            await self._release_lock(job.job_id)

    async def _save_job_history(
        self, job: BatchJob, start: datetime, end: datetime, success: bool, result: dict[str, Any]
    ):
        """Save job execution to audit store."""
        try:
            from infrastructure.event_store.append_only_store import get_audit_store

            store = get_audit_store()
            if store:
                await store.append(
                    "batch_job_history",
                    {
                        "job_id": job.job_id,
                        "job_name": job.name,
                        "command_type": job.command_type,
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                        "duration_seconds": (end - start).total_seconds(),
                        "success": success,
                        "result": result,
                        "legal_entity_id": str(job.legal_entity_id),
                    },
                )
        except Exception as e:
            logger.error(f"Failed to save job history: {e}")

    def _on_job_executed(self, event):
        logger.info(f"APScheduler job executed: {event.job_id}")

    def _on_job_error(self, event):
        logger.error(f"APScheduler job error: {event.job_id}, exception: {event.exception}")

    async def add_job(self, job: BatchJob) -> str:
        """Add a scheduled job to the scheduler."""
        if not self.scheduler:
            raise RuntimeError("Scheduler not initialized")
        trigger = CronTrigger.from_crontab(job.cron_expression)
        aps_job = self.scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            args=[job],
            id=job.job_id,
            name=job.name,
            replace_existing=True,
        )
        self._jobs_registry[job.job_id] = job
        logger.info(f"Added scheduled job: {job.name} with cron {job.cron_expression}")
        return aps_job.id

    async def remove_job(self, job_id: str):
        """Remove a scheduled job."""
        if self.scheduler:
            self.scheduler.remove_job(job_id)
        if job_id in self._jobs_registry:
            del self._jobs_registry[job_id]
        logger.info(f"Removed job {job_id}")

    async def pause_job(self, job_id: str):
        if self.scheduler:
            self.scheduler.pause_job(job_id)
        if job_id in self._jobs_registry:
            self._jobs_registry[job_id].is_active = False

    async def resume_job(self, job_id: str):
        if self.scheduler:
            self.scheduler.resume_job(job_id)
        if job_id in self._jobs_registry:
            self._jobs_registry[job_id].is_active = True

    async def run_job_now(self, job_id: str):
        """Run a job immediately (one-time)."""
        job = self._jobs_registry.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        asyncio.create_task(self._execute_job(job))

    async def list_jobs(self) -> list[dict[str, Any]]:
        """List all registered jobs."""
        result = []
        for job_id, job in self._jobs_registry.items():
            result.append(
                {
                    "job_id": job_id,
                    "name": job.name,
                    "command_type": job.command_type,
                    "cron": job.cron_expression,
                    "is_active": job.is_active,
                    "last_run": job.last_run.isoformat() if job.last_run else None,
                    "last_status": job.last_status,
                    "last_output": job.last_output,
                }
            )
        return result


# ============================================================================
# DEFAULT JOB DEFINITIONS
# ============================================================================


def create_default_jobs(legal_entity_id: UUID) -> list[BatchJob]:
    """Create default batch jobs for a legal entity."""
    current_time = datetime.now(UTC)
    return [
        BatchJob(
            job_id=f"depreciation_monthly_{legal_entity_id}",
            name="Monthly Depreciation Run",
            command_type="depreciation.run",
            cron_expression="0 2 1 * *",  # 02:00 on day 1 of every month
            params={"post_to_ledger": True},
            legal_entity_id=legal_entity_id,
            timeout_minutes=30,
        ),
        BatchJob(
            job_id=f"period_close_monthly_{legal_entity_id}",
            name="Monthly Period Close",
            command_type="period.close",
            cron_expression="0 3 2 * *",  # 03:00 on day 2 of every month
            params={"fiscal_year": current_time.year, "period": current_time.month},
            legal_entity_id=legal_entity_id,
            timeout_minutes=60,
        ),
        BatchJob(
            job_id=f"integrity_check_daily_{legal_entity_id}",
            name="Daily Hash Chain Integrity Check",
            command_type="audit.verify_integrity",
            cron_expression="0 4 * * *",  # 04:00 daily
            params={},
            legal_entity_id=legal_entity_id,
            timeout_minutes=15,
        ),
        BatchJob(
            job_id=f"ar_collection_reminder_{legal_entity_id}",
            name="AR Collection Reminder",
            command_type="ar.collection.reminder",
            cron_expression="0 8 * * *",  # 08:00 daily
            params={},
            legal_entity_id=legal_entity_id,
            timeout_minutes=10,
        ),
        BatchJob(
            job_id=f"bank_reconciliation_auto_{legal_entity_id}",
            name="Auto Bank Reconciliation",
            command_type="bank.reconcile.auto",
            cron_expression="0 5 * * *",  # 05:00 daily
            params={},
            legal_entity_id=legal_entity_id,
            timeout_minutes=20,
        ),
    ]


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_scheduler_instance: BatchJobScheduler | None = None


async def get_batch_scheduler() -> BatchJobScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = BatchJobScheduler()
        await _scheduler_instance.initialize()
    return _scheduler_instance


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_scheduler():
    scheduler = await get_batch_scheduler()
    return scheduler


# ============================================================================
# STANDALONE RUNNER (opsional, untuk process terpisah)
# ============================================================================


async def run_scheduler_standalone():
    """Run scheduler as standalone process."""
    scheduler = await get_batch_scheduler()
    logger.info("Batch job scheduler running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await scheduler.shutdown()


def main():
    """Entry point utama menggunakan asyncio.Runner untuk kepatuhan async modern."""
    with asyncio.Runner() as runner:
        runner.run(run_scheduler_standalone())


if __name__ == "__main__":
    main()

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["BatchJob", "BatchJobScheduler", "get_batch_scheduler", "get_scheduler"]
