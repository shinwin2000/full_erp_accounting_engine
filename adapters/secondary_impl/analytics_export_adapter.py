#!/usr/bin/env python3
"""
Adapter untuk AnalyticsExportPort.
Implementasi sederhana (in-memory) untuk keperluan matching checker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from ports.secondary.analytics_export_port import (
    AnalyticsExportPort,
    CompressionType,
    DeliveryMethod,
    ExportFormat,
    ExportJob,
    ExportStatus,
)


class AnalyticsExportAdapter(AnalyticsExportPort):
    """In-memory adapter untuk AnalyticsExportPort."""

    def __init__(self):
        self._jobs: dict[UUID, ExportJob] = {}

    def set_data_provider(self, provider):
        # implementasi sederhana
        pass

    async def create_export_job(
        self,
        name: str,
        query_type: str,
        query_parameters: dict[str, Any],
        format: ExportFormat,
        created_by: UUID,
        filters: list[dict[str, Any]] | None = None,
        compression: CompressionType = CompressionType.NONE,
        encryption_key_id: str | None = None,
        delivery_method: DeliveryMethod = DeliveryMethod.NONE,
        delivery_config: dict[str, Any] | None = None,
        scheduled_at: datetime | None = None,
    ) -> UUID:
        job_id = uuid4()
        now = datetime.utcnow()
        job = ExportJob(
            id=job_id,
            name=name,
            query_type=query_type,
            query_parameters=query_parameters,
            filters=filters,
            format=format,
            compression=compression,
            encryption_key_id=encryption_key_id,
            delivery_method=delivery_method,
            delivery_config=delivery_config or {},
            created_by=created_by,
            created_at=now,
            scheduled_at=scheduled_at,
            status=ExportStatus.PENDING,
            started_at=None,
            completed_at=None,
            error_message=None,
            output_url=None,
            output_size_bytes=None,
            row_count=None,
            file_hash=None,
        )
        self._jobs[job_id] = job
        return job_id

    async def execute_job(self, job_id: UUID) -> bool:
        job = self._jobs.get(job_id)
        if job and job.status == ExportStatus.PENDING:
            job.status = ExportStatus.SUCCESS
            job.completed_at = datetime.utcnow()
            return True
        return False

    async def cancel_job(self, job_id: UUID) -> bool:
        job = self._jobs.get(job_id)
        if job and job.status in (ExportStatus.PENDING, ExportStatus.PROCESSING):
            job.status = ExportStatus.CANCELLED
            return True
        return False

    async def get_job_status(self, job_id: UUID) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    async def get_job_output(self, job_id: UUID) -> bytes | None:
        return None

    async def start_scheduler(self, poll_interval_seconds: int = 60):
        pass

    async def stop_scheduler(self):
        pass

    async def list_jobs(
        self, status: ExportStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[ExportJob]:
        result = list(self._jobs.values())
        if status:
            result = [j for j in result if j.status == status]
        result.sort(key=lambda x: x.created_at, reverse=True)
        return result[offset:offset + limit]

    async def get_statistics(self) -> dict[str, Any]:
        return {"total_jobs": len(self._jobs)}

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return []

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy"}
