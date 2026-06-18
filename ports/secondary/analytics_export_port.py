#!/usr/bin/env python3
"""
Module: analytics_export_port.py
Layer: Ports (Secondary)
Responsibility: Antarmuka dan implementasi in-memory untuk export data analitik.
               Mendukung ekspor ke berbagai format (CSV, JSON, Excel, Parquet),
               kompresi (ZIP, GZIP), enkripsi AES, scheduling, delivery (email,
               FTP, S3), audit trail, dan monitoring.
Audit: Setiap export yang dijalankan tercatat.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import io
import json
import logging
import secrets
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC as PBKDF2

logger = logging.getLogger(__name__)


class ExportFormat(Enum):
    """Format ekspor yang didukung."""

    CSV = "csv"
    JSON = "json"
    EXCEL = "excel"
    PARQUET = "parquet"
    HTML = "html"


class CompressionType(Enum):
    """Jenis kompresi."""

    NONE = "none"
    GZIP = "gzip"
    ZIP = "zip"


class DeliveryMethod(Enum):
    """Metode pengiriman hasil ekspor."""

    NONE = "none"
    EMAIL = "email"
    FTP = "ftp"
    S3 = "s3"
    LOCAL_PATH = "local_path"
    WEBHOOK = "webhook"


class ExportStatus(Enum):
    """Status ekspor."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExportJob:
    """Job ekspor."""

    id: UUID
    name: str
    query_type: str
    query_parameters: dict[str, Any]
    filters: list[dict[str, Any]] | None
    format: ExportFormat
    compression: CompressionType
    encryption_key_id: str | None
    delivery_method: DeliveryMethod
    delivery_config: dict[str, Any]
    created_by: UUID
    created_at: datetime
    scheduled_at: datetime | None
    status: ExportStatus
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    output_url: str | None
    output_size_bytes: int | None
    row_count: int | None
    file_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "query_type": self.query_type,
            "format": self.format.value,
            "compression": self.compression.value,
            "delivery_method": self.delivery_method.value,
            "created_by": str(self.created_by),
            "created_at": self.created_at.isoformat(),
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "output_url": self.output_url,
            "output_size_bytes": self.output_size_bytes,
            "row_count": self.row_count,
            "file_hash": self.file_hash,
        }


class AnalyticsExportPort:
    """
    In-memory analytics export service.
    """

    def __init__(self):
        self._jobs: dict[UUID, ExportJob] = {}
        self._query_data_provider: (
            Callable[[str, dict[str, Any], list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]
            | None
        ) = None
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._scheduler_task: asyncio.Task | None = None
        self._running = False

    # ==================== HELPER ====================

    async def _log_audit(self, action: str, job_id: UUID, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "job_id": str(job_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"EXPORT AUDIT: {action} on {job_id}")

    async def _encrypt_data(self, data: bytes, key_id: str, password: str | None = None) -> bytes:
        """Enkripsi data dengan AES-256-GCM (simulasi)."""
        if not password:
            # Use derived key from key_id
            password = key_id + "default_salt_32bytes_long!!"
        salt = secrets.token_bytes(16)
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(password.encode())
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        result = salt + nonce + ciphertext
        return result

    async def _compress_data(self, data: bytes, compression: CompressionType) -> bytes:
        if compression == CompressionType.GZIP:
            return gzip.compress(data, compresslevel=6)
        elif compression == CompressionType.ZIP:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("data", data)
            return buf.getvalue()
        else:
            return data

    async def _export_csv(self, data: list[dict[str, Any]]) -> str:
        output = io.StringIO()
        if not data:
            return ""
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        return output.getvalue()

    async def _export_json(self, data: list[dict[str, Any]]) -> str:
        return json.dumps(data, indent=2, default=str)

    async def _export_excel(self, data: list[dict[str, Any]]) -> bytes:
        """Simulate Excel export (return CSV as fallback)."""
        # In real implementation, use openpyxl or xlsxwriter
        csv_content = await self._export_csv(data)
        return csv_content.encode()

    async def _export_html(self, data: list[dict[str, Any]]) -> str:
        if not data:
            return "<html><body><p>No data</p></body></html>"
        headers = data[0].keys()
        rows_html = ""
        for row in data:
            rows_html += "<tr>"
            for h in headers:
                rows_html += f"<td>{row.get(h, '')}</td>"
            rows_html += "</tr>"
        html = f"""<html>
        <head><title>Export Data</title></head>
        <body>
            <table border="1">
                <thead><tr>{"".join(f"<th>{h}</th>" for h in headers)}</tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            <p>Generated at: {datetime.now().isoformat()}</p>
        </body>
        </html>"""
        return html

    # ==================== DATA PROVIDER ====================

    def set_data_provider(
        self,
        provider: Callable[
            [str, dict[str, Any], list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]
        ],
    ):
        """Set data provider untuk mengambil data berdasarkan query."""
        self._query_data_provider = provider

    # ==================== EXPORT JOB MANAGEMENT ====================

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
        """Buat job ekspor baru."""
        job_id = uuid4()
        now = datetime.now(UTC)
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
        async with self._lock:
            self._jobs[job_id] = job
        await self._log_audit(
            "CREATE",
            job_id,
            {
                "name": name,
                "query_type": query_type,
                "format": format.value,
            },
        )
        return job_id

    async def execute_job(self, job_id: UUID) -> bool:
        """Eksekusi job ekspor (ambil data, export, compress, encrypt, deliver)."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status != ExportStatus.PENDING:
            return False

        job.status = ExportStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        await self._log_audit("START", job_id, {})

        try:
            # 1. Ambil data dari query provider
            if not self._query_data_provider:
                raise Exception("No data provider configured")
            data = await self._query_data_provider(
                job.query_type, job.query_parameters, job.filters or []
            )
            row_count = len(data)

            # 2. Export data
            if job.format == ExportFormat.CSV:
                content = await self._export_csv(data)
                output_data = content.encode()
            elif job.format == ExportFormat.JSON:
                content = await self._export_json(data)
                output_data = content.encode()
            elif job.format == ExportFormat.EXCEL:
                output_data = await self._export_excel(data)
            elif job.format == ExportFormat.HTML:
                content = await self._export_html(data)
                output_data = content.encode()
            else:
                output_data = json.dumps(data, default=str).encode()

            # 3. Compress
            output_data = await self._compress_data(output_data, job.compression)

            # 4. Encrypt
            if job.encryption_key_id:
                output_data = await self._encrypt_data(output_data, job.encryption_key_id)

            # 5. Compute hash
            file_hash = hashlib.sha256(output_data).hexdigest()

            # 6. Deliver
            output_url = await self._deliver(job, output_data)

            # 7. Update job
            job.status = ExportStatus.SUCCESS
            job.completed_at = datetime.now(UTC)
            job.output_url = output_url
            job.output_size_bytes = len(output_data)
            job.row_count = row_count
            job.file_hash = file_hash

            await self._log_audit(
                "SUCCESS",
                job_id,
                {
                    "row_count": row_count,
                    "size_bytes": len(output_data),
                    "output_url": output_url,
                },
            )
            return True

        except Exception as e:
            job.status = ExportStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.error_message = str(e)
            await self._log_audit("FAILED", job_id, {"error": str(e)})
            return False

    async def _deliver(self, job: ExportJob, data: bytes) -> str:
        """Kirim hasil ekspor sesuai delivery method."""
        method = job.delivery_method
        config = job.delivery_config
        if method == DeliveryMethod.NONE:
            # Simpan in-memory, return "memory://{job_id}"
            return f"memory://{job.id}"
        elif method == DeliveryMethod.EMAIL:
            # Simulate email send
            recipients = config.get("recipients", [])
            subject = config.get("subject", f"Export {job.name}")
            logger.info(f"EMAIL would be sent to {recipients} with attachment of {len(data)} bytes")
            return f"email://{','.join(recipients)}"
        elif method == DeliveryMethod.FTP:
            logger.info(f"FTP upload to {config.get('host')}:{config.get('port')}")
            return f"ftp://{config.get('host')}/{config.get('path')}"
        elif method == DeliveryMethod.S3:
            bucket = config.get("bucket")
            key = config.get("key", f"exports/{job.id}.{job.format.value}")
            logger.info(f"S3 upload to s3://{bucket}/{key}")
            return f"s3://{bucket}/{key}"
        elif method == DeliveryMethod.LOCAL_PATH:
            path = config.get("path")
            with open(path, "wb") as f:
                f.write(data)
            return f"file://{path}"
        elif method == DeliveryMethod.WEBHOOK:
            url = config.get("url")
            logger.info(f"Webhook POST to {url} with data length {len(data)}")
            return f"webhook://{url}"
        else:
            raise ValueError(f"Unknown delivery method: {method}")

    async def cancel_job(self, job_id: UUID) -> bool:
        """Batalkan job yang masih pending atau processing."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status not in (ExportStatus.PENDING, ExportStatus.PROCESSING):
            return False
        job.status = ExportStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        await self._log_audit("CANCELLED", job_id, {})
        return True

    async def get_job_status(self, job_id: UUID) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.to_dict()

    async def get_job_output(self, job_id: UUID) -> bytes | None:
        """Ambil output (hanya untuk delivery method NONE / in-memory)."""
        job = self._jobs.get(job_id)
        if not job or job.status != ExportStatus.SUCCESS:
            return None
        if not job.output_url or not job.output_url.startswith("memory://"):
            # For real storage, would need to fetch from S3 etc.
            return None
        # In-memory storage not persisted, so cannot retrieve actual bytes
        return None

    # ==================== SCHEDULER ====================

    async def start_scheduler(self, poll_interval_seconds: int = 60):
        """Start background scheduler to process scheduled jobs."""
        if self._running:
            return
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(poll_interval_seconds))
        logger.info("Export scheduler started")

    async def _scheduler_loop(self, interval: int):
        while self._running:
            await asyncio.sleep(interval)
            await self._process_scheduled_jobs()

    async def _process_scheduled_jobs(self):
        now = datetime.now(UTC)
        jobs_to_run = []
        async with self._lock:
            for job in self._jobs.values():
                if (
                    job.status == ExportStatus.PENDING
                    and job.scheduled_at
                    and job.scheduled_at <= now
                ):
                    jobs_to_run.append(job.id)
        for job_id in jobs_to_run:
            await self.execute_job(job_id)

    async def stop_scheduler(self):
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("Export scheduler stopped")

    # ==================== QUERY ====================

    async def list_jobs(
        self, status: ExportStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[ExportJob]:
        result = list(self._jobs.values())
        if status:
            result = [j for j in result if j.status == status]
        result.sort(key=lambda x: x.created_at, reverse=True)
        return result[offset : offset + limit]

    async def get_statistics(self) -> dict[str, Any]:
        jobs = list(self._jobs.values())
        total = len(jobs)
        success = sum(1 for j in jobs if j.status == ExportStatus.SUCCESS)
        failed = sum(1 for j in jobs if j.status == ExportStatus.FAILED)
        pending = sum(1 for j in jobs if j.status == ExportStatus.PENDING)
        processing = sum(1 for j in jobs if j.status == ExportStatus.PROCESSING)
        by_format = {f.value: sum(1 for j in jobs if j.format == f) for f in ExportFormat}
        return {
            "total_jobs": total,
            "success": success,
            "failed": failed,
            "pending": pending,
            "processing": processing,
            "by_format": by_format,
            "scheduler_running": self._running,
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_jobs": len(self._jobs),
            "scheduler_running": self._running,
            "audit_log_size": len(self._audit_log),
            "data_provider_configured": self._query_data_provider is not None,
        }
