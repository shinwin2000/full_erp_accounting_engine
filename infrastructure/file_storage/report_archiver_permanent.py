#!/usr/bin/env python3
"""
Module: report_archiver_permanent.py
Layer: Infrastructure (File Storage)
Responsibility: Layanan untuk mengarsipkan laporan keuangan dan dokumen compliance
               secara permanen ke cold storage (Glacier) atau long-term storage.
               Mendukung archiving dengan retention policy, integrity hashing,
               dan metadata untuk pencarian. Juga menyediakan fungsi untuk
               restore laporan yang diarsipkan.
Dependencies:
- asyncio, logging, datetime, shutil
- infrastructure.file_storage.glacier_cold_storage_adapter (GlacierColdStorageAdapter)
- infrastructure.file_storage.s3_adapter (S3FileStorageAdapter)
- infrastructure.file_storage.file_integrity_hasher (FileIntegrityHasher)
- infrastructure.caching.redis_manager (RedisManager)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap operasi archive dan restore dicatat untuk compliance.
       Laporan keuangan harus diarsipkan minimal 7 tahun sesuai PSAK.
"""

from __future__ import annotations

import io
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.event_store.append_only_store import get_event_store
from infrastructure.file_storage.file_integrity_hasher import FileIntegrityHasher

# Internal dependencies
from infrastructure.file_storage.glacier_cold_storage_adapter import (
    GlacierColdStorageAdapter,
    get_glacier_cold_storage_adapter,
)
from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter, get_s3_storage_adapter
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Retention periods (days)
RETENTION_FINANCIAL_REPORT = 365 * 7  # 7 years (PSAK)
RETENTION_TAX_REPORT = 365 * 10  # 10 years (tax law)
RETENTION_AUDIT_TRAIL = 365 * 10  # 10 years
RETENTION_PERMANENT = 365 * 100  # 100 years (practically permanent)

# Report types
REPORT_TYPES = {
    "financial_statement": RETENTION_FINANCIAL_REPORT,
    "annual_report": RETENTION_FINANCIAL_REPORT,
    "tax_return": RETENTION_TAX_REPORT,
    "audit_report": RETENTION_AUDIT_TRAIL,
    "spt_ppn": RETENTION_TAX_REPORT,
    "spt_pph": RETENTION_TAX_REPORT,
    "period_close_report": RETENTION_FINANCIAL_REPORT,
    "bank_reconciliation": RETENTION_FINANCIAL_REPORT,
    "inventory_valuation": RETENTION_FINANCIAL_REPORT,
    "fixed_asset_register": RETENTION_FINANCIAL_REPORT,
}

# Archive status
ARCHIVE_STATUS_PENDING = "pending"
ARCHIVE_STATUS_COMPLETED = "completed"
ARCHIVE_STATUS_FAILED = "failed"
ARCHIVE_STATUS_RESTORING = "restoring"
ARCHIVE_STATUS_RESTORED = "restored"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class ReportArchiverError(Exception):
    """Base exception untuk report archiver."""

    pass


class ReportNotFoundError(ReportArchiverError):
    """Report tidak ditemukan."""

    pass


class ArchiveFailedError(ReportArchiverError):
    """Gagal mengarsipkan report."""

    pass


class RestoreFailedError(ReportArchiverError):
    """Gagal merestore report."""

    pass


# ============================================================================
# REPORT ARCHIVER
# ============================================================================


class ReportArchiverPermanent:
    """
    Layanan untuk mengarsipkan laporan secara permanen.

    Fitur:
    - Archive report ke cold storage (Glacier)
    - Retention policy berdasarkan jenis laporan
    - Integrity hashing untuk verifikasi
    - Metadata indexing untuk pencarian
    - Restore archived reports
    - Batch archiving
    """

    def __init__(
        self,
        cold_storage: GlacierColdStorageAdapter | None = None,
        hot_storage: S3FileStorageAdapter | None = None,
    ):
        self._cold_storage = cold_storage
        self._hot_storage = hot_storage
        self._hasher = FileIntegrityHasher()
        self._redis_manager: RedisManager | None = None
        self._archive_jobs: dict[str, dict] = {}
        self._archive_index: dict[str, dict] = {}

    async def _get_cold_storage(self) -> GlacierColdStorageAdapter:
        if self._cold_storage is None:
            self._cold_storage = await get_glacier_cold_storage_adapter()
        return self._cold_storage

    async def _get_hot_storage(self) -> S3FileStorageAdapter:
        if self._hot_storage is None:
            self._hot_storage = await get_s3_storage_adapter()
        return self._hot_storage

    async def _get_redis(self) -> RedisManager:
        if self._redis_manager is None:
            self._redis_manager = await get_redis_manager()
        return self._redis_manager

    def _get_retention_days(self, report_type: str) -> int:
        """Get retention period for report type."""
        return REPORT_TYPES.get(report_type, RETENTION_FINANCIAL_REPORT)

    def _generate_archive_key(
        self, report_type: str, report_id: str, legal_entity_id: str, period: str
    ) -> str:
        """Generate archive key for the report."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"reports/{report_type}/{legal_entity_id}/{period}/{timestamp}_{report_id}.pdf"

    async def archive_report(
        self,
        report_content: bytes,
        report_type: str,
        report_id: str,
        report_name: str,
        legal_entity_id: UUID,
        period: str,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """
        Archive a report to permanent storage.

        Args:
            report_content: Report file content as bytes
            report_type: Type of report (financial_statement, tax_return, etc.)
            report_id: Unique identifier for this report
            report_name: Display name of the report
            legal_entity_id: Legal entity ID
            period: Period string (e.g., "2024-12", "FY2024")
            metadata: Additional metadata

        Returns:
            Archive info dictionary
        """
        # Compute hash for integrity
        content_hash = self._hasher.compute_hash(report_content)
        retention_days = self._get_retention_days(report_type)
        archive_key = self._generate_archive_key(
            report_type, report_id, str(legal_entity_id), period
        )

        # Prepare archive metadata
        archive_metadata = {
            "report_type": report_type,
            "report_id": report_id,
            "report_name": report_name,
            "legal_entity_id": str(legal_entity_id),
            "period": period,
            "content_hash": content_hash,
            "original_size": len(report_content),
            "retention_days": retention_days,
            "retention_until": (datetime.now(UTC) + timedelta(days=retention_days)).isoformat(),
            "archived_at": datetime.now(UTC).isoformat(),
            "archived_by": metadata.get("archived_by", "system") if metadata else "system",
        }
        if metadata:
            archive_metadata.update(metadata)

        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(report_content)
            tmp_path = Path(tmp.name)

        try:
            # Upload to hot storage first (for quick access)
            hot_storage = await self._get_hot_storage()
            hot_uri = await hot_storage.upload(
                file_content=io.BytesIO(report_content),
                file_name=f"{archive_key}",
                content_type="application/pdf",
                metadata=archive_metadata,
            )

            # Then archive to cold storage
            cold_storage = await self._get_cold_storage()
            cold_uri = await cold_storage.upload(
                file_content=io.BytesIO(report_content),
                file_name=f"{archive_key}",
                metadata=archive_metadata,
            )

            # Store archive index
            archive_id = str(uuid4())
            self._archive_index[archive_id] = {
                "archive_id": archive_id,
                "report_type": report_type,
                "report_id": report_id,
                "report_name": report_name,
                "legal_entity_id": str(legal_entity_id),
                "period": period,
                "hot_uri": hot_uri,
                "cold_uri": cold_uri,
                "content_hash": content_hash,
                "retention_days": retention_days,
                "retention_until": archive_metadata["retention_until"],
                "archived_at": archive_metadata["archived_at"],
                "status": ARCHIVE_STATUS_COMPLETED,
            }

            # Record audit
            await self._create_audit_record(
                "archive", archive_id, report_type, report_id, legal_entity_id
            )

            logger.info(f"Report archived: {report_name} ({report_type}) to {cold_uri}")

            # Clean up temp file
            tmp_path.unlink()

            return self._archive_index[archive_id]

        except Exception as e:
            logger.error(f"Failed to archive report: {e}")
            raise ArchiveFailedError(f"Archive failed: {e}") from e

    async def archive_report_from_file(
        self,
        file_path: Path,
        report_type: str,
        report_id: str,
        report_name: str,
        legal_entity_id: UUID,
        period: str,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """
        Archive a report from local file path.
        """
        with open(file_path, "rb") as f:
            content = f.read()
        return await self.archive_report(
            content, report_type, report_id, report_name, legal_entity_id, period, metadata
        )

    async def restore_report(self, archive_id: str, target_path: Path | None = None) -> bytes:
        """
        Restore an archived report.

        Args:
            archive_id: Archive ID from archive_report
            target_path: Optional path to save the restored file

        Returns:
            Report content as bytes
        """
        archive_info = self._archive_index.get(archive_id)
        if not archive_info:
            # Try to load from database
            archive_info = await self._load_archive_metadata(archive_id)
            if not archive_info:
                raise ReportNotFoundError(f"Archive {archive_id} not found")

        cold_storage = await self._get_cold_storage()

        try:
            # Try to restore from cold storage
            cold_uri = archive_info["cold_uri"]
            content = await cold_storage.download(cold_uri)

            # Verify integrity
            stored_hash = archive_info["content_hash"]
            if not self._hasher.verify_hash(content, stored_hash):
                await trigger_alert(
                    title="Archived Report Integrity Check Failed",
                    message=f"Report {archive_info['report_name']} hash mismatch",
                    severity="critical",
                    source="ReportArchiverPermanent",
                )
                raise RestoreFailedError("Integrity check failed")

            # Save to target path if provided
            if target_path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "wb") as f:
                    f.write(content)

            # Update status
            archive_info["status"] = ARCHIVE_STATUS_RESTORED
            archive_info["restored_at"] = datetime.now(UTC).isoformat()

            await self._create_audit_record(
                "restore",
                archive_id,
                archive_info["report_type"],
                archive_info["report_id"],
                UUID(archive_info["legal_entity_id"]),
            )

            logger.info(f"Report restored: {archive_info['report_name']}")
            return content

        except Exception as e:
            logger.error(f"Failed to restore report: {e}")
            raise RestoreFailedError(f"Restore failed: {e}") from e

    async def get_archive_info(self, archive_id: str) -> dict[str, Any]:
        """
        Get information about an archived report.
        """
        info = self._archive_index.get(archive_id)
        if not info:
            info = await self._load_archive_metadata(archive_id)
            if info:
                self._archive_index[archive_id] = info
        return info

    async def list_archives(
        self,
        report_type: str | None = None,
        legal_entity_id: UUID | None = None,
        period: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List archived reports.
        """
        results = []
        for archive_id, info in self._archive_index.items():
            if report_type and info.get("report_type") != report_type:
                continue
            if legal_entity_id and info.get("legal_entity_id") != str(legal_entity_id):
                continue
            if period and info.get("period") != period:
                continue
            results.append(info)
            if len(results) >= limit:
                break

        # Sort by archived_at desc
        results.sort(key=lambda x: x.get("archived_at", ""), reverse=True)
        return results

    async def delete_archive(self, archive_id: str, deleted_by: UUID) -> bool:
        """
        Delete an archived report (only if retention period has passed).
        """
        archive_info = await self.get_archive_info(archive_id)
        if not archive_info:
            return False

        # Check retention period
        retention_until = archive_info.get("retention_until")
        if retention_until:
            retention_date = datetime.fromisoformat(retention_until)
            if datetime.now(UTC) < retention_date:
                logger.warning(f"Cannot delete archive {archive_id} - retention period not over")
                return False

        cold_storage = await self._get_cold_storage()
        cold_uri = archive_info["cold_uri"]

        try:
            # Delete from cold storage
            await cold_storage.delete(cold_uri)

            # Delete from hot storage if exists
            if archive_info.get("hot_uri"):
                hot_storage = await self._get_hot_storage()
                await hot_storage.delete(archive_info["hot_uri"])

            # Remove from index
            if archive_id in self._archive_index:
                del self._archive_index[archive_id]

            await self._create_audit_record(
                "delete",
                archive_id,
                archive_info["report_type"],
                archive_info["report_id"],
                deleted_by,
            )

            logger.info(f"Archive deleted: {archive_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete archive: {e}")
            return False

    async def archive_batch(self, reports: list[dict]) -> list[dict]:
        """
        Archive multiple reports in batch.

        Args:
            reports: List of report dictionaries with keys:
                     content, report_type, report_id, report_name,
                     legal_entity_id, period, metadata

        Returns:
            List of archive info dictionaries
        """
        results = []
        for report in reports:
            try:
                result = await self.archive_report(
                    report_content=report["content"],
                    report_type=report["report_type"],
                    report_id=report["report_id"],
                    report_name=report["report_name"],
                    legal_entity_id=report["legal_entity_id"],
                    period=report["period"],
                    metadata=report.get("metadata"),
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to archive report {report.get('report_id')}: {e}")
                results.append({"error": str(e), "report_id": report.get("report_id")})

        return results

    async def generate_archive_report(
        self, start_date: datetime, end_date: datetime, legal_entity_id: UUID
    ) -> dict[str, Any]:
        """
        Generate a report of all archives in date range.
        """
        archives = []
        for archive_id, info in self._archive_index.items():
            archived_at = info.get("archived_at")
            if archived_at:
                archived_date = datetime.fromisoformat(archived_at)
                if start_date <= archived_date <= end_date:
                    if info.get("legal_entity_id") == str(legal_entity_id):
                        archives.append(info)

        return {
            "legal_entity_id": str(legal_entity_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_archives": len(archives),
            "archives": archives[:100],  # Limit to 100 for report
        }

    async def _load_archive_metadata(self, archive_id: str) -> dict | None:
        """
        Load archive metadata from persistent storage.
        """
        # In production, load from database
        return None

    async def _create_audit_record(
        self, action: str, archive_id: str, report_type: str, report_id: str, performed_by: UUID
    ) -> None:
        """Create audit record for archive operation."""
        try:
            store = await get_event_store()
            await store.append(
                stream_name="audit_report_archive",
                event_data={
                    "action": action,
                    "archive_id": archive_id,
                    "report_type": report_type,
                    "report_id": report_id,
                    "performed_by": str(performed_by),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                event_type="report.archive",
                metadata={"source": "ReportArchiverPermanent"},
            )
        except Exception as e:
            logger.warning(f"Failed to create audit record: {e}")

    async def get_stats(self) -> dict[str, Any]:
        """Get archiver statistics."""
        total_archives = len(self._archive_index)
        by_type = {}
        for info in self._archive_index.values():
            report_type = info.get("report_type", "unknown")
            by_type[report_type] = by_type.get(report_type, 0) + 1

        return {
            "total_archives": total_archives,
            "archives_by_type": by_type,
            "active_archive_jobs": len(self._archive_jobs),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_report_archiver: ReportArchiverPermanent | None = None


async def get_report_archiver() -> ReportArchiverPermanent:
    """Get singleton instance of ReportArchiverPermanent."""
    global _report_archiver
    if _report_archiver is None:
        _report_archiver = ReportArchiverPermanent()
    return _report_archiver


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_report_archiver_dep():
    """FastAPI dependency for report archiver."""
    return await get_report_archiver()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ARCHIVE_STATUS_COMPLETED",
    "ARCHIVE_STATUS_FAILED",
    "ARCHIVE_STATUS_PENDING",
    "ARCHIVE_STATUS_RESTORED",
    "ARCHIVE_STATUS_RESTORING",
    "ArchiveFailedError",
    "ReportArchiverError",
    "ReportArchiverPermanent",
    "ReportNotFoundError",
    "RestoreFailedError",
    "get_report_archiver",
    "get_report_archiver_dep",
]
