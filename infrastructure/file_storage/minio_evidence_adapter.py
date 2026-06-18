#!/usr/bin/env python3
"""
Module: minio_evidence_adapter.py
Layer: Infrastructure (File Storage)
Responsibility: Implementasi file storage adapter untuk MinIO (S3-compatible)
               khusus untuk menyimpan bukti transaksi (evidence) seperti
               faktur pajak, bukti pembayaran, dokumen kontrak, dll.
               Mendukung versioning, retention policy, dan integrity hashing.
Dependencies:
- minio (python-minio) - optional
- asyncio, io, mimetypes
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
- infrastructure.file_storage.file_integrity_hasher
Audit: Setiap evidence yang disimpan dicatat dengan hash integrity.
       Evidence tidak dapat dihapus setelah retention period.
"""

from __future__ import annotations

import io
import mimetypes
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO
from uuid import uuid4

# Try to import minio
try:
    from minio import Minio
    from minio.error import S3Error

    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False
    Minio = None
    S3Error = Exception

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.file_storage.abstract_port import (
    BaseFileStorageAdapter,
    FileDownloadError,
    FileNotFoundError,
    FileStorageError,
    FileUploadError,
)
from infrastructure.file_storage.file_integrity_hasher import FileIntegrityHasher
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_MINIO_CONFIG = {
    "endpoint": "localhost:9000",
    "access_key": "minioadmin",
    "secret_key": "minioadmin",
    "secure": False,
    "bucket": "erp-evidence",
    "region": "ap-southeast-1",
    "retention_days": 365 * 7,  # 7 years retention for evidence
    "enable_versioning": True,
    "presigned_url_expiration": 3600,
}

# ============================================================================
# MINIO EVIDENCE ADAPTER
# ============================================================================


class MinioEvidenceAdapter(BaseFileStorageAdapter):
    """
    Implementasi file storage adapter untuk MinIO (S3-compatible).
    Khusus untuk menyimpan bukti transaksi dengan retention policy.

    Fitur:
    - Upload/download evidence files
    - Versioning untuk setiap evidence
    - Retention policy (7 tahun untuk compliance)
    - Integrity hashing (SHA-256)
    - Metadata untuk linking ke transaksi
    - Presigned URLs untuk akses aman
    """

    def __init__(self, config_path: str = "config_files/filestorage_config.yaml"):
        super().__init__()
        self.config = self._load_config(config_path)
        self._endpoint = self.config.get("endpoint", DEFAULT_MINIO_CONFIG["endpoint"])
        self._access_key = self.config.get("access_key", DEFAULT_MINIO_CONFIG["access_key"])
        self._secret_key = self.config.get("secret_key", DEFAULT_MINIO_CONFIG["secret_key"])
        self._secure = self.config.get("secure", DEFAULT_MINIO_CONFIG["secure"])
        self._bucket = self.config.get("bucket", DEFAULT_MINIO_CONFIG["bucket"])
        self._region = self.config.get("region", DEFAULT_MINIO_CONFIG["region"])
        self._retention_days = self.config.get(
            "retention_days", DEFAULT_MINIO_CONFIG["retention_days"]
        )
        self._enable_versioning = self.config.get(
            "enable_versioning", DEFAULT_MINIO_CONFIG["enable_versioning"]
        )
        self._presigned_expiration = self.config.get(
            "presigned_url_expiration", DEFAULT_MINIO_CONFIG["presigned_url_expiration"]
        )
        self._client = None
        self._hasher = FileIntegrityHasher()

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            minio_config = config.get("minio", {})
            result = DEFAULT_MINIO_CONFIG.copy()
            result.update(minio_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load MinIO config, using defaults: {e}")
            return DEFAULT_MINIO_CONFIG.copy()

    async def _get_client(self) -> Minio | None:
        """Get or create MinIO client."""
        if not MINIO_AVAILABLE:
            logger.error("MinIO client not available. Install with: pip install minio")
            raise FileStorageError("MinIO adapter not available (minio missing)")

        if self._client is None:
            try:
                self._client = Minio(
                    self._endpoint,
                    access_key=self._access_key,
                    secret_key=self._secret_key,
                    secure=self._secure,
                    region=self._region,
                )
                # Ensure bucket exists
                if not self._client.bucket_exists(self._bucket):
                    self._client.make_bucket(self._bucket)
                    if self._enable_versioning:
                        self._client.set_bucket_versioning(self._bucket, True)
                    logger.info(f"Created bucket: {self._bucket}")
            except Exception as e:
                logger.error(f"Failed to initialize MinIO client: {e}")
                raise FileStorageError(f"MinIO client initialization failed: {e}") from e

        return self._client

    def _generate_key(self, transaction_type: str, transaction_id: str, file_name: str) -> str:
        """
        Generate object key for evidence.
        Format: {transaction_type}/{transaction_id}/{timestamp}_{uuid}_{file_name}
        """
        timestamp = datetime.now(UTC).strftime("%Y/%m/%d/%H%M%S")
        unique_id = str(uuid4())[:8]
        return f"{transaction_type}/{transaction_id}/{timestamp}_{unique_id}_{file_name}"

    def _get_content_type(self, file_name: str) -> str:
        """Get MIME type from file extension."""
        content_type, _ = mimetypes.guess_type(file_name)
        return content_type or "application/octet-stream"

    async def upload_evidence(
        self,
        file_content: BinaryIO,
        file_name: str,
        transaction_type: str,
        transaction_id: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """
        Upload evidence file untuk transaksi.

        Args:
            file_content: File content as binary stream
            file_name: Original file name
            transaction_type: Type of transaction (e.g., "invoice", "payment", "contract")
            transaction_id: ID of the transaction
            metadata: Additional metadata

        Returns:
            File URI
        """
        client = await self._get_client()
        key = self._generate_key(transaction_type, transaction_id, file_name)
        content_type = self._get_content_type(file_name)

        # Read content and compute hash
        content = file_content.read()
        if isinstance(content, str):
            content = content.encode("utf-8")

        content_hash = self._hasher.compute_hash(content)
        content_length = len(content)

        # Build metadata
        all_metadata = {
            "transaction_type": transaction_type,
            "transaction_id": transaction_id,
            "original_filename": file_name,
            "content_hash": content_hash,
            "content_length": str(content_length),
            "uploaded_at": datetime.now(UTC).isoformat(),
        }
        if metadata:
            all_metadata.update(metadata)

        # Upload to MinIO
        try:
            result = client.put_object(
                bucket_name=self._bucket,
                object_name=key,
                data=io.BytesIO(content),
                length=content_length,
                content_type=content_type,
                metadata=all_metadata,
            )

            uri = f"minio://{self._bucket}/{key}"
            logger.info(
                f"Evidence uploaded to MinIO: {uri} (size: {content_length} bytes, hash: {content_hash[:16]}...)"
            )

            # Verify integrity
            await self._verify_upload_integrity(uri, content_hash)

            return uri

        except S3Error as e:
            logger.error(f"MinIO upload failed: {e}")
            raise FileUploadError(f"Failed to upload evidence: {e}") from e

    async def download_evidence(self, file_uri: str, verify_hash: bool = True) -> BinaryIO:
        """
        Download evidence file from MinIO.

        Args:
            file_uri: File URI from upload
            verify_hash: Verify content integrity against stored hash

        Returns:
            Binary stream of file content
        """
        client = await self._get_client()
        bucket, key = self._parse_uri(file_uri)

        try:
            response = client.get_object(bucket, key)
            content = response.read()
            response.close()
            response.release_conn()

            # Verify integrity
            if verify_hash:
                stored_hash = response.metadata.get("content_hash")
                if stored_hash:
                    computed_hash = self._hasher.compute_hash(content)
                    if not self._hasher.verify_hash(content, stored_hash):
                        await trigger_alert(
                            title="Evidence Integrity Check Failed",
                            message=f"File {file_uri} hash mismatch. Possible corruption or tampering.",
                            severity="critical",
                            source="MinioEvidenceAdapter",
                        )
                        raise FileStorageError("Evidence integrity check failed")

            logger.info(f"Evidence downloaded from MinIO: {file_uri} (size: {len(content)} bytes)")
            return io.BytesIO(content)

        except S3Error as e:
            if e.code == "NoSuchKey":
                raise FileNotFoundError(f"Evidence not found: {file_uri}") from e
            logger.error(f"MinIO download failed: {e}")
            raise FileDownloadError(f"Failed to download evidence: {e}") from e

    async def _verify_upload_integrity(self, file_uri: str, expected_hash: str) -> bool:
        """Verify uploaded file integrity."""
        try:
            metadata = await self.get_metadata(file_uri)
            stored_hash = metadata.get("metadata", {}).get("content_hash")
            return stored_hash == expected_hash
        except Exception:
            return False

    async def upload(
        self,
        file_content: BinaryIO,
        file_name: str,
        content_type: str = None,
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
    ) -> str:
        """
        Generic upload (uses upload_evidence with transaction_type="general").
        """
        return await self.upload_evidence(
            file_content, file_name, "general", str(uuid4()), metadata
        )

    async def download(self, file_uri: str) -> BinaryIO:
        """Generic download (with hash verification)."""
        return await self.download_evidence(file_uri, verify_hash=True)

    async def delete(self, file_uri: str) -> bool:
        """
        Delete evidence (may be restricted by retention policy).
        """
        client = await self._get_client()
        bucket, key = self._parse_uri(file_uri)

        # Check retention period
        metadata = await self.get_metadata(file_uri)
        uploaded_at = metadata.get("metadata", {}).get("uploaded_at")
        if uploaded_at:
            try:
                upload_date = datetime.fromisoformat(uploaded_at)
                retention_end = upload_date + timedelta(days=self._retention_days)
                if datetime.now(UTC) < retention_end:
                    logger.warning(
                        f"Cannot delete evidence {file_uri} due to retention policy (expires: {retention_end})"
                    )
                    return False
            except (ValueError, TypeError):
                pass

        try:
            client.remove_object(bucket, key)
            logger.info(f"Evidence deleted from MinIO: {file_uri}")
            return True
        except S3Error as e:
            logger.error(f"MinIO delete failed: {e}")
            return False

    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        """
        Get evidence metadata.
        """
        client = await self._get_client()
        bucket, key = self._parse_uri(file_uri)

        try:
            stat = client.stat_object(bucket, key)

            return {
                "size": stat.size,
                "content_type": stat.content_type,
                "last_modified": stat.last_modified.isoformat() if stat.last_modified else None,
                "etag": stat.etag,
                "metadata": stat.metadata,
                "bucket": bucket,
                "key": key,
                "uri": file_uri,
            }
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise FileNotFoundError(f"Evidence not found: {file_uri}") from e
            raise FileStorageError(f"Failed to get metadata: {e}") from e

    async def exists(self, file_uri: str) -> bool:
        """Check if evidence exists."""
        try:
            await self.get_metadata(file_uri)
            return True
        except FileNotFoundError:
            return False

    async def generate_presigned_url(self, file_uri: str, expiration_seconds: int = 3600) -> str:
        """
        Generate presigned URL for secure temporary access.
        """
        client = await self._get_client()
        bucket, key = self._parse_uri(file_uri)

        try:
            url = client.presigned_get_object(
                bucket_name=bucket, object_name=key, expires=expiration_seconds
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise FileStorageError(f"Presigned URL generation failed: {e}") from e

    async def list_files(self, prefix: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """
        List evidence files with given prefix.
        """
        client = await self._get_client()

        try:
            objects = client.list_objects(self._bucket, prefix=prefix, recursive=False)
            files = []
            for i, obj in enumerate(objects):
                if i >= limit:
                    break
                files.append(
                    {
                        "key": obj.object_name,
                        "size": obj.size,
                        "last_modified": obj.last_modified.isoformat()
                        if obj.last_modified
                        else None,
                        "etag": obj.etag,
                        "uri": f"minio://{self._bucket}/{obj.object_name}",
                    }
                )
            return files
        except S3Error as e:
            logger.error(f"Failed to list files: {e}")
            raise FileStorageError(f"List files failed: {e}") from e

    async def get_size(self, file_uri: str) -> int:
        """Get file size in bytes."""
        metadata = await self.get_metadata(file_uri)
        return metadata.get("size", 0)

    async def copy(self, source_uri: str, destination_uri: str) -> bool:
        """Copy evidence within MinIO."""
        client = await self._get_client()
        src_bucket, src_key = self._parse_uri(source_uri)
        dst_bucket, dst_key = self._parse_uri(destination_uri)

        try:
            client.copy_object(dst_bucket, dst_key, f"{src_bucket}/{src_key}")
            logger.info(f"Evidence copied: {source_uri} -> {destination_uri}")
            return True
        except S3Error as e:
            logger.error(f"MinIO copy failed: {e}")
            return False

    async def move(self, source_uri: str, destination_uri: str) -> bool:
        """Move evidence within MinIO."""
        if await self.copy(source_uri, destination_uri):
            return await self.delete(source_uri)
        return False

    async def get_upload_url(
        self,
        file_name: str,
        content_type: str = "application/octet-stream",
        expiration_seconds: int = 3600,
    ) -> dict[str, str]:
        """Generate presigned URL for client-side upload."""
        client = await self._get_client()
        key = f"uploads/{datetime.now().strftime('%Y/%m/%d')}/{uuid4()}_{file_name}"

        try:
            url = client.presigned_put_object(
                bucket_name=self._bucket, object_name=key, expires=expiration_seconds
            )
            return {
                "url": url,
                "key": key,
                "bucket": self._bucket,
                "expires_in": expiration_seconds,
            }
        except S3Error as e:
            logger.error(f"Failed to generate upload URL: {e}")
            raise FileStorageError(f"Upload URL generation failed: {e}") from e

    def _parse_uri(self, uri: str) -> tuple:
        """Parse minio://bucket/key URI."""
        if uri.startswith("minio://"):
            parts = uri[8:].split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
            return parts[0], ""
        raise ValueError(f"Invalid MinIO URI: {uri}")

    async def close(self) -> None:
        """Close MinIO client (no explicit close needed for MinIO)."""
        self._client = None


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_minio_adapter: MinioEvidenceAdapter | None = None


async def get_minio_evidence_adapter() -> MinioEvidenceAdapter:
    """Get singleton instance of MinioEvidenceAdapter."""
    global _minio_adapter
    if _minio_adapter is None:
        _minio_adapter = MinioEvidenceAdapter()
    return _minio_adapter


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["MinioEvidenceAdapter", "get_minio_evidence_adapter"]
