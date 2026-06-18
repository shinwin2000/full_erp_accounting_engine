#!/usr/bin/env python3
"""
Module: minio_evidence_store.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menyimpan file bukti (evidence) ke MinIO/S3 dengan kredensial aman.
Security: Tidak ada hardcoded secret. Semua kredensial dari environment atau config.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

# Optional import for MinIO client
try:
    from minio import Minio
    from minio.error import S3Error

    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False
    Minio = None
    S3Error = Exception

logger = logging.getLogger(__name__)


class MinIOConfigError(Exception):
    """Konfigurasi MinIO tidak lengkap atau salah."""

    pass


class MinIOOperationError(Exception):
    """Gagal melakukan operasi MinIO."""

    pass


class MinioEvidenceStore:
    """
    Adapter untuk MinIO object storage.
    Kredensial diambil dari environment variables:
    - MINIO_ENDPOINT (default: localhost:9000)
    - MINIO_ACCESS_KEY (wajib)
    - MINIO_SECRET_KEY (wajib)
    - MINIO_SECURE (default: False, gunakan 'true' untuk HTTPS)
    - MINIO_REGION (opsional)
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = False,
        region: str | None = None,
    ):
        """
        Inisialisasi adapter MinIO.
        Jika parameter tidak diberikan, akan membaca dari environment.
        """
        self.endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY")
        secure_flag = os.getenv("MINIO_SECURE", "false").lower() == "true"
        self.secure = secure or secure_flag
        self.region = region or os.getenv("MINIO_REGION")

        self._client = None
        self._lock = asyncio.Lock()

        self._validate_config()

    def _validate_config(self):
        """Pastikan kredensial tersedia."""
        if not self.access_key or not self.secret_key:
            raise MinIOConfigError(
                "MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be set in environment "
                "or passed to constructor."
            )
        if not MINIO_AVAILABLE:
            logger.warning("MinIO Python client not installed. Install with: pip install minio")
            # Tidak raise error, tapi operasi akan gagal jika dipanggil.

    def _get_client(self) -> Any:
        """Lazy initialization MinIO client."""
        if self._client is not None:
            return self._client
        if not MINIO_AVAILABLE:
            raise MinIOOperationError(
                "MinIO client library not installed. Please install 'minio' package."
            )
        try:
            self._client = Minio(
                endpoint=self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
                region=self.region,
            )
            logger.info("MinIO client initialized for endpoint %s", self.endpoint)
        except Exception as e:
            raise MinIOOperationError(f"Failed to create MinIO client: {e}") from e
        return self._client

    async def _ensure_bucket(self, bucket: str):
        """Buat bucket jika belum ada (async wrapper)."""
        client = self._get_client()
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                logger.info("Bucket '%s' created", bucket)
        except S3Error as e:
            raise MinIOOperationError(f"Failed to ensure bucket '{bucket}': {e}") from e

    async def upload(
        self,
        bucket: str,
        key: str,
        data: bytes,
        metadata: dict[str, str] | None = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload file ke bucket MinIO.
        Returns object URI (s3://bucket/key).
        """
        if not data:
            raise ValueError("Data cannot be empty")
        async with self._lock:
            client = self._get_client()
            await self._ensure_bucket(bucket)
            try:
                # Put object (synchronous call, run in executor)
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: client.put_object(
                        bucket_name=bucket,
                        object_name=key,
                        data=bytes(data),
                        length=len(data),
                        content_type=content_type,
                        metadata=metadata or {},
                    ),
                )
                logger.info(
                    "Uploaded %s to bucket %s (etag: %s)",
                    key,
                    bucket,
                    result.etag
                )
                return f"s3://{bucket}/{key}"
            except S3Error as e:
                logger.error("Upload failed: %s", e)
                raise MinIOOperationError(f"Upload failed: {e}") from e
            except Exception as e:
                logger.exception("Unexpected error during upload")
                raise MinIOOperationError(f"Upload error: {e}") from e

    async def download(self, bucket: str, key: str) -> bytes:
        """
        Download file dari bucket MinIO.
        Returns raw bytes.
        """
        async with self._lock:
            client = self._get_client()
            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.get_object(bucket, key),
                )
                data = await loop.run_in_executor(None, response.read)
                response.close()
                response.release_conn()
                logger.info(
                    "Downloaded %s from bucket %s (%d bytes)",
                    key,
                    bucket,
                    len(data)
                )
                return data
            except S3Error as e:
                logger.error("Download failed: %s", e)
                raise MinIOOperationError(f"Download failed: {e}") from e
            except Exception as e:
                logger.exception("Unexpected error during download")
                raise MinIOOperationError(f"Download error: {e}") from e

    async def delete(self, bucket: str, key: str) -> bool:
        """
        Hapus file dari bucket.
        Returns True jika berhasil (atau file tidak ada).
        """
        async with self._lock:
            client = self._get_client()
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: client.remove_object(bucket, key))
                logger.info("Deleted %s from bucket %s", key, bucket)
                return True
            except S3Error as e:
                if e.code == "NoSuchKey":
                    logger.warning("Object %s not found in bucket %s", key, bucket)
                    return True  # sudah tidak ada, anggap sukses
                logger.error("Delete failed: %s", e)
                raise MinIOOperationError(f"Delete failed: {e}") from e
            except Exception as e:
                logger.exception("Unexpected error during delete")
                raise MinIOOperationError(f"Delete error: {e}") from e

    async def exists(self, bucket: str, key: str) -> bool:
        """Cek apakah object ada di bucket."""
        async with self._lock:
            client = self._get_client()
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: client.stat_object(bucket, key))
                return True
            except S3Error as e:
                if e.code == "NoSuchKey":
                    return False
                raise MinIOOperationError(f"Exists check failed: {e}") from e

    async def get_presigned_url(
        self,
        bucket: str,
        key: str,
        expires_seconds: int = 3600,
        method: str = "GET",
    ) -> str:
        """
        Generate presigned URL untuk sementara akses.
        """
        async with self._lock:
            client = self._get_client()
            try:
                loop = asyncio.get_running_loop()
                url = await loop.run_in_executor(
                    None,
                    lambda: client.presigned_get_object(bucket, key, expires=expires_seconds)
                    if method == "GET"
                    else client.presigned_put_object(bucket, key, expires=expires_seconds),
                )
                return url
            except S3Error as e:
                raise MinIOOperationError(f"Presigned URL failed: {e}") from e


# ============================================================================
# SINGLETON / DEPENDENCY INJECTION
# ============================================================================

_default_store: MinioEvidenceStore | None = None


def get_minio_evidence_store() -> MinioEvidenceStore:
    """
    Mendapatkan instance singleton MinioEvidenceStore.
    Kredensial diambil dari environment saat pertama kali dipanggil.
    """
    global _default_store
    if _default_store is None:
        _default_store = MinioEvidenceStore()
    return _default_store


__all__ = [
    "MinIOConfigError",
    "MinIOOperationError",
    "MinioEvidenceStore",
    "get_minio_evidence_store",
]
