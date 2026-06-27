#!/usr/bin/env python3
"""
Module: s3_file_storage_adapter_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menyimpan file ke AWS S3.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class S3FileStorageAdapter:
    """
    Adapter untuk AWS S3.
    Stub, hanya log.
    """

    def __init__(self, bucket: str | None = None, region: str | None = None):
        self.bucket = bucket or os.getenv("S3_BUCKET", "default-bucket")
        self.region = region or os.getenv("S3_REGION", "ap-southeast-1")
        self._audit_log: list[dict[str, Any]] = []
        self._cleanup_running = False

    async def upload(self, key: str, data: bytes, metadata: dict | None = None) -> str:
        logger.info(f"Uploading {key} to S3 bucket {self.bucket} ({len(data)} bytes)")
        return f"s3://{self.bucket}/{key}"

    async def download(self, key: str) -> bytes:
        logger.info(f"Downloading {key} from S3")
        return b"mock_s3_content"

    async def delete(self, key: str) -> bool:
        logger.info(f"Deleting {key} from S3")
        return True

    # ===== New missing methods =====

    async def create_version(self, key: str, data: bytes, metadata: dict | None = None) -> dict[str, Any]:
        """Create a new version of a file (if versioning enabled)."""
        version_id = str(uuid4())
        logger.info(f"Creating version {version_id} for {key}")
        self._audit_log.append({
            "action": "create_version",
            "key": key,
            "version_id": version_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        return {"version_id": version_id, "key": key, "bucket": self.bucket}

    async def download_range(self, key: str, start: int, end: int) -> bytes:
        """Download a byte range of a file."""
        logger.info(f"Downloading range {start}-{end} of {key}")
        return b"mock_range_content"

    async def generate_presigned_url(self, key: str, expires_in: int = 3600, method: str = "GET") -> str:
        """Generate a pre-signed URL for temporary access."""
        logger.info(f"Generating presigned URL for {key} (expires {expires_in}s)")
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}?X-Amz-Expires={expires_in}&mock=1"

    async def get_audit_log(self, key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get audit log entries for file operations."""
        logs = self._audit_log
        if key:
            logs = [l for l in logs if l.get("key") == key]
        return logs[-limit:]

    async def get_metadata(self, key: str) -> dict[str, Any]:
        """Get metadata of a file."""
        logger.info(f"Getting metadata for {key}")
        return {
            "key": key,
            "size": 1024,
            "last_modified": datetime.utcnow().isoformat(),
            "etag": "mock_etag",
            "content_type": "application/octet-stream",
            "metadata": {"mock": "value"}
        }

    async def get_statistics(self) -> dict[str, Any]:
        """Get storage statistics (total files, total size, etc.)."""
        logger.info("Getting S3 statistics")
        return {
            "total_files": 100,
            "total_size_bytes": 104857600,
            "bucket": self.bucket,
            "region": self.region
        }

    async def get_versions(self, key: str, limit: int = 10) -> list[dict[str, Any]]:
        """List versions of a file."""
        logger.info(f"Getting versions for {key}")
        return [
            {"version_id": "v1", "size": 1024, "last_modified": datetime.utcnow().isoformat()},
            {"version_id": "v2", "size": 2048, "last_modified": datetime.utcnow().isoformat()}
        ][:limit]

    async def health_check(self) -> dict[str, Any]:
        """Perform health check (e.g., connectivity to S3)."""
        logger.info("S3 health check")
        return {"status": "healthy", "bucket": self.bucket, "region": self.region}

    async def list_files(self, prefix: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List files in the bucket with pagination."""
        logger.info(f"Listing files with prefix '{prefix}' (limit={limit}, offset={offset})")
        return [
            {"key": f"file_{i}.txt", "size": 100 + i, "last_modified": datetime.utcnow().isoformat()}
            for i in range(offset, min(offset + limit, 10))
        ]

    async def start_cleanup_task(self, interval_seconds: int = 86400) -> None:
        """Start a background task to clean up old files (stub)."""
        self._cleanup_running = True
        logger.info(f"Starting cleanup task every {interval_seconds}s")

    async def stop_cleanup(self) -> None:
        """Stop the cleanup task."""
        self._cleanup_running = False
        logger.info("Stopping cleanup task")

    async def update_metadata(self, key: str, metadata: dict[str, Any]) -> bool:
        """Update metadata of a file."""
        logger.info(f"Updating metadata for {key}: {metadata}")
        self._audit_log.append({
            "action": "update_metadata",
            "key": key,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat()
        })
        return True

    async def upload_chunked_start(self, key: str, total_size: int, metadata: dict[str, Any] | None = None) -> str:
        """Start a multipart upload and return upload ID."""
        upload_id = str(uuid4())
        logger.info(f"Starting chunked upload for {key} (total {total_size} bytes), upload_id={upload_id}")
        return upload_id

    async def upload_chunked_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> dict[str, Any]:
        """Upload a part of a multipart upload."""
        logger.info(f"Uploading part {part_number} for {key}, upload_id={upload_id}")
        return {"etag": f"etag_part_{part_number}", "part_number": part_number}

    async def upload_chunked_complete(self, key: str, upload_id: str, parts: list[dict[str, Any]]) -> str:
        """Complete a multipart upload."""
        logger.info(f"Completing upload {upload_id} for {key} with {len(parts)} parts")
        return f"s3://{self.bucket}/{key}"

    async def verify_presigned_url(self, url: str, expected_key: str | None = None) -> bool:
        """Verify that a presigned URL is valid and points to the expected key."""
        logger.info(f"Verifying presigned URL for key {expected_key}")
        # Stub: always valid if URL contains the key
        if expected_key and expected_key not in url:
            return False
        return True


S3FileStorageAdapterImpl = S3FileStorageAdapter

__all__ = ["S3FileStorageAdapter", "S3FileStorageAdapterImpl"]
