#!/usr/bin/env python3
"""
Module: glacier_cold_storage_adapter.py
Layer: Infrastructure (File Storage)
Responsibility: Implementasi file storage adapter untuk AWS Glacier (cold storage)
               untuk arsip jangka panjang (audit trail, backup, dokumen legal).
               Mendukung upload ke vault, retrieval (standard/expedited/bulk),
               dan inventory management. Biaya rendah untuk penyimpanan jangka panjang.
Dependencies:
- boto3 (aioboto3) - optional
- asyncio, logging, datetime
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap operasi archive (upload, retrieval, delete) dicatat.
       Retrieval time dicatat untuk compliance.
"""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

# Try to import boto3/aioboto3
try:
    import aioboto3
    from botocore.exceptions import ClientError

    GLACIER_AVAILABLE = True
except ImportError:
    GLACIER_AVAILABLE = False
    aioboto3 = None
    ClientError = Exception

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.file_storage.abstract_port import (
    BaseFileStorageAdapter,
    FileDownloadError,
    FileNotFoundError,
    FileStorageError,
    FileUploadError,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_GLACIER_CONFIG = {
    "vault_name": "erp-archive",
    "region": "ap-southeast-1",
    "access_key": None,
    "secret_key": None,
    "retrieval_type": "Standard",  # Standard, Expedited, Bulk
    "inventory_refresh_hours": 24,
    "archive_retention_days": 3650,  # 10 years
}

# Retrieval time estimates (seconds)
RETRIEVAL_TIME_ESTIMATES = {
    "Standard": 360,  # 3-5 hours
    "Expedited": 60,  # 1-5 minutes
    "Bulk": 14400,  # 5-12 hours
}

# ============================================================================
# GLACIER ADAPTER
# ============================================================================


class GlacierColdStorageAdapter(BaseFileStorageAdapter):
    """
    Implementasi file storage adapter untuk AWS Glacier.

    Fitur:
    - Upload archive ke Glacier vault
    - Initiate retrieval jobs (Standard, Expedited, Bulk)
    - Check job status
    - Download retrieved archive
    - Delete archive
    - Inventory management
    """

    def __init__(self, config_path: str = "config_files/filestorage_config.yaml"):
        super().__init__()
        self.config = self._load_config(config_path)
        self._vault_name = self.config.get("vault_name", DEFAULT_GLACIER_CONFIG["vault_name"])
        self._region = self.config.get("region", DEFAULT_GLACIER_CONFIG["region"])
        self._access_key = self.config.get("access_key")
        self._secret_key = self.config.get("secret_key")
        self._retrieval_type = self.config.get(
            "retrieval_type", DEFAULT_GLACIER_CONFIG["retrieval_type"]
        )
        self._inventory_refresh_hours = self.config.get(
            "inventory_refresh_hours", DEFAULT_GLACIER_CONFIG["inventory_refresh_hours"]
        )
        self._session = None
        self._client = None
        self._jobs_cache: dict[str, dict] = {}
        self._inventory_cache: dict[str, Any] = {}
        self._last_inventory_refresh: datetime | None = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            glacier_config = config.get("glacier", {})
            result = DEFAULT_GLACIER_CONFIG.copy()
            result.update(glacier_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load Glacier config, using defaults: {e}")
            return DEFAULT_GLACIER_CONFIG.copy()

    async def _get_client(self):
        """Get or create Glacier client."""
        if not GLACIER_AVAILABLE:
            raise FileStorageError("Glacier adapter not available (aioboto3 missing)")

        if self._session is None:
            self._session = aioboto3.Session()

        if self._client is None:
            kwargs = {"region_name": self._region}
            if self._access_key and self._secret_key:
                kwargs["aws_access_key_id"] = self._access_key
                kwargs["aws_secret_access_key"] = self._secret_key

            self._client = await self._session.client("glacier", **kwargs).__aenter__()

        return self._client

    async def _close_client(self):
        """Close Glacier client."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None

    async def upload(
        self,
        file_content: BinaryIO,
        file_name: str,
        content_type: str = None,
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
    ) -> str:
        """
        Upload archive to Glacier vault.
        """
        client = await self._get_client()

        # Read content
        content = file_content.read()
        if isinstance(content, str):
            content = content.encode("utf-8")

        archive_description = f"{file_name}|{metadata.get('description', '') if metadata else ''}"

        try:
            response = await client.upload_archive(
                vaultName=self._vault_name,
                body=io.BytesIO(content),
                archiveDescription=archive_description[:1024],  # Max 1024 chars
            )

            archive_id = response["archiveId"]
            uri = f"glacier://{self._vault_name}/{archive_id}"

            logger.info(f"Archive uploaded to Glacier: {uri} (size: {len(content)} bytes)")

            # Store metadata mapping
            await self._store_archive_metadata(archive_id, file_name, metadata)

            return uri

        except ClientError as e:
            logger.error(f"Glacier upload failed: {e}")
            raise FileUploadError(f"Failed to upload to Glacier: {e}") from e

    async def _store_archive_metadata(
        self, archive_id: str, file_name: str, metadata: dict | None = None
    ) -> None:
        """Store archive metadata for tracking."""
        # In production, store in database
        logger.debug(f"Archive metadata stored for {archive_id}: {file_name}")

    async def download(self, file_uri: str) -> BinaryIO:
        """
        Download archive from Glacier (initiates retrieval if needed).
        """
        client = await self._get_client()
        vault_name, archive_id = self._parse_uri(file_uri)

        # Check if already retrieved and in cache
        job_key = f"{vault_name}:{archive_id}"
        if job_key in self._jobs_cache:
            job = self._jobs_cache[job_key]
            if job["status"] == "Succeeded":
                # Download from job output
                return await self._download_from_job_output(job["job_id"], vault_name)
            elif job["status"] == "InProgress":
                raise FileDownloadError(
                    f"Retrieval in progress. Estimated completion: {job['estimated_completion']}"
                )

        # Initiate new retrieval job
        job_id = await self._initiate_retrieval(vault_name, archive_id)

        # Wait for job completion (asynchronously)
        asyncio.create_task(self._poll_job_status(job_id, vault_name, archive_id))

        raise FileDownloadError(
            f"Retrieval initiated for {archive_id}. Please check back later. "
            f"Job ID: {job_id}, Estimated time: {RETRIEVAL_TIME_ESTIMATES.get(self._retrieval_type, 360)} seconds"
        )

    async def _initiate_retrieval(self, vault_name: str, archive_id: str) -> str:
        """Initiate archive retrieval job."""
        client = await self._get_client()

        response = await client.initiate_job(
            vaultName=vault_name,
            jobParameters={
                "Type": "archive-retrieval",
                "ArchiveId": archive_id,
                "Tier": self._retrieval_type,
            },
        )

        job_id = response["jobId"]

        self._jobs_cache[f"{vault_name}:{archive_id}"] = {
            "job_id": job_id,
            "status": "InProgress",
            "estimated_completion": datetime.now(UTC)
            + timedelta(seconds=RETRIEVAL_TIME_ESTIMATES.get(self._retrieval_type, 360)),
        }

        logger.info(f"Initiated retrieval for {archive_id}, job: {job_id}")
        return job_id

    async def _poll_job_status(self, job_id: str, vault_name: str, archive_id: str) -> None:
        """Poll job status until completion."""
        client = await self._get_client()
        key = f"{vault_name}:{archive_id}"

        while True:
            try:
                response = await client.describe_job(vaultName=vault_name, jobId=job_id)

                status = response["StatusCode"]
                if status == "Succeeded":
                    self._jobs_cache[key]["status"] = "Succeeded"
                    logger.info(f"Retrieval job completed for {archive_id}")
                    break
                elif status == "Failed":
                    self._jobs_cache[key]["status"] = "Failed"
                    logger.error(
                        f"Retrieval job failed for {archive_id}: {response.get('StatusMessage')}"
                    )
                    break

                await asyncio.sleep(60)  # Poll every minute

            except Exception as e:
                logger.error(f"Error polling job status: {e}")
                await asyncio.sleep(120)

    async def _download_from_job_output(self, job_id: str, vault_name: str) -> BinaryIO:
        """Download output from completed retrieval job."""
        client = await self._get_client()

        response = await client.get_job_output(vaultName=vault_name, jobId=job_id)

        content = await response["body"].read()
        return io.BytesIO(content)

    async def delete(self, file_uri: str) -> bool:
        """
        Delete archive from Glacier.
        """
        client = await self._get_client()
        vault_name, archive_id = self._parse_uri(file_uri)

        try:
            await client.delete_archive(vaultName=vault_name, archiveId=archive_id)
            logger.info(f"Archive deleted from Glacier: {file_uri}")
            return True
        except ClientError as e:
            logger.error(f"Glacier delete failed: {e}")
            return False

    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        """
        Get archive metadata from inventory.
        """
        vault_name, archive_id = self._parse_uri(file_uri)

        # Refresh inventory if needed
        await self._refresh_inventory(vault_name)

        archive_info = self._inventory_cache.get("archives", {}).get(archive_id)
        if not archive_info:
            raise FileNotFoundError(f"Archive not found: {file_uri}")

        return {
            "archive_id": archive_id,
            "size": archive_info.get("Size", 0),
            "description": archive_info.get("ArchiveDescription", ""),
            "creation_date": archive_info.get("CreationDate"),
            "uri": file_uri,
        }

    async def _refresh_inventory(self, vault_name: str) -> None:
        """Refresh vault inventory."""
        now = datetime.now(UTC)
        if (
            self._last_inventory_refresh
            and (now - self._last_inventory_refresh).total_seconds()
            < self._inventory_refresh_hours * 3600
        ):
            return

        client = await self._get_client()

        try:
            response = await client.describe_vault(vaultName=vault_name)
            inventory_date = response.get("LastInventoryDate")

            if not inventory_date:
                logger.warning("No inventory available for vault, initiating inventory job")
                await self._initiate_inventory_job(vault_name)
                return

            # Get inventory
            inventory_response = await client.get_vault_inventory(
                vaultName=vault_name, inventoryDate=inventory_date
            )

            self._inventory_cache = {
                "vault_name": vault_name,
                "inventory_date": inventory_date,
                "archives": {},
            }

            for archive in inventory_response.get("ArchiveList", []):
                self._inventory_cache["archives"][archive["ArchiveId"]] = archive

            self._last_inventory_refresh = now
            logger.info(
                f"Vault inventory refreshed: {len(self._inventory_cache['archives'])} archives"
            )

        except ClientError as e:
            logger.error(f"Failed to refresh inventory: {e}")

    async def _initiate_inventory_job(self, vault_name: str) -> None:
        """Initiate inventory retrieval job."""
        client = await self._get_client()

        response = await client.initiate_job(
            vaultName=vault_name, jobParameters={"Type": "inventory-retrieval"}
        )

        logger.info(f"Initiated inventory retrieval job: {response['jobId']}")

    async def exists(self, file_uri: str) -> bool:
        """Check if archive exists."""
        try:
            await self.get_metadata(file_uri)
            return True
        except FileNotFoundError:
            return False

    async def generate_presigned_url(self, file_uri: str, expiration_seconds: int = 3600) -> str:
        """Generate presigned URL (not supported directly by Glacier, use retrieval)."""
        # For Glacier, we need to initiate retrieval first
        raise NotImplementedError(
            "Presigned URLs not supported for Glacier. Use download() instead."
        )

    async def list_files(self, prefix: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """List archives in vault."""
        vault_name = self._vault_name
        await self._refresh_inventory(vault_name)

        archives = []
        for archive_id, archive in self._inventory_cache.get("archives", {}).items():
            if prefix and not archive.get("ArchiveDescription", "").startswith(prefix):
                continue
            archives.append(
                {
                    "archive_id": archive_id,
                    "size": archive.get("Size", 0),
                    "description": archive.get("ArchiveDescription", ""),
                    "creation_date": archive.get("CreationDate"),
                    "uri": f"glacier://{vault_name}/{archive_id}",
                }
            )
            if len(archives) >= limit:
                break

        return archives

    async def get_size(self, file_uri: str) -> int:
        """Get archive size in bytes."""
        metadata = await self.get_metadata(file_uri)
        return metadata.get("size", 0)

    async def copy(self, source_uri: str, destination_uri: str) -> bool:
        """Copy not supported for Glacier."""
        raise NotImplementedError("Copy not supported for Glacier")

    async def move(self, source_uri: str, destination_uri: str) -> bool:
        """Move not supported for Glacier."""
        raise NotImplementedError("Move not supported for Glacier")

    async def get_upload_url(
        self,
        file_name: str,
        content_type: str = "application/octet-stream",
        expiration_seconds: int = 3600,
    ) -> dict[str, str]:
        """Get upload URL (not supported for Glacier)."""
        raise NotImplementedError(
            "Direct upload URLs not supported for Glacier. Use upload() instead."
        )

    def _parse_uri(self, uri: str) -> tuple:
        """Parse glacier://vault_name/archive_id URI."""
        if uri.startswith("glacier://"):
            parts = uri[9:].split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
            return parts[0], ""
        raise ValueError(f"Invalid Glacier URI: {uri}")

    async def get_job_status(self, archive_id: str) -> dict | None:
        """Get retrieval job status for an archive."""
        key = f"{self._vault_name}:{archive_id}"
        return self._jobs_cache.get(key)

    async def close(self) -> None:
        """Close Glacier client."""
        await self._close_client()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_glacier_adapter: GlacierColdStorageAdapter | None = None


async def get_glacier_cold_storage_adapter() -> GlacierColdStorageAdapter:
    """Get singleton instance of GlacierColdStorageAdapter."""
    global _glacier_adapter
    if _glacier_adapter is None:
        _glacier_adapter = GlacierColdStorageAdapter()
    return _glacier_adapter


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["GlacierColdStorageAdapter", "get_glacier_cold_storage_adapter"]
