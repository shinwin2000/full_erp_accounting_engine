#!/usr/bin/env python3
"""
Module: abstract_port.py
Layer: Infrastructure (File Storage)
Responsibility: Mendefinisikan abstract base class untuk file storage adapter.
               Port ini digunakan oleh application layer untuk menyimpan dan
               mengambil file (bukti transaksi, lampiran invoice, laporan, dll)
               tanpa tergantung pada implementasi konkret (S3, Minio, Local, dll).
Dependencies:
- abc, typing, pathlib, uuid
- infrastructure.file_storage.file_integrity_hasher (optional)
Audit: Setiap operasi file (upload, download, delete) harus dicatat
       untuk compliance dan audit trail.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class FileStorageError(Exception):
    """Base exception untuk file storage."""

    pass


class FileNotFoundError(FileStorageError):
    """File tidak ditemukan."""

    pass


class FileUploadError(FileStorageError):
    """Error saat upload file."""

    pass


class FileDownloadError(FileStorageError):
    """Error saat download file."""

    pass


class FileStorageNotConfiguredError(FileStorageError):
    """File storage belum dikonfigurasi."""

    pass


# ============================================================================
# ABSTRACT PORT
# ============================================================================


class FileStoragePort(ABC):
    """
    Abstract port untuk file storage.

    Implementasi konkret:
    - S3FileStorageAdapter (AWS S3)
    - MinioFileStorageAdapter (Minio)
    - LocalFileStorageAdapter (Local filesystem)
    - GlacierFileStorageAdapter (AWS Glacier)
    """

    @abstractmethod
    async def upload(
        self,
        file_content: BinaryIO,
        file_name: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
    ) -> str:
        """
        Upload file ke storage.

        Args:
            file_content: File content as binary stream
            file_name: Original file name
            content_type: MIME type
            metadata: Additional metadata (e.g., uploaded_by, document_type)
            bucket: Optional bucket name (uses default if not specified)

        Returns:
            File URI/path that can be used to retrieve the file
        """
        pass

    @abstractmethod
    async def download(self, file_uri: str) -> BinaryIO:
        """
        Download file dari storage.

        Args:
            file_uri: File URI returned from upload

        Returns:
            Binary stream of file content

        Raises:
            FileNotFoundError: If file does not exist
        """
        pass

    @abstractmethod
    async def delete(self, file_uri: str) -> bool:
        """
        Delete file dari storage.

        Args:
            file_uri: File URI to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        """
        Get file metadata.

        Args:
            file_uri: File URI

        Returns:
            Dictionary with metadata (size, content_type, last_modified, etc.)
        """
        pass

    @abstractmethod
    async def exists(self, file_uri: str) -> bool:
        """
        Check if file exists.

        Args:
            file_uri: File URI

        Returns:
            True if file exists
        """
        pass

    @abstractmethod
    async def generate_presigned_url(self, file_uri: str, expiration_seconds: int = 3600) -> str:
        """
        Generate temporary URL for secure access.

        Args:
            file_uri: File URI
            expiration_seconds: URL validity duration

        Returns:
            Presigned URL (temporary, secure)
        """
        pass

    @abstractmethod
    async def list_files(self, prefix: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """
        List files matching prefix.

        Args:
            prefix: Key prefix to filter
            limit: Maximum number of files to return

        Returns:
            List of file metadata dictionaries
        """
        pass

    @abstractmethod
    async def get_size(self, file_uri: str) -> int:
        """
        Get file size in bytes.

        Args:
            file_uri: File URI

        Returns:
            File size in bytes
        """
        pass

    @abstractmethod
    async def copy(self, source_uri: str, destination_uri: str) -> bool:
        """
        Copy file within storage.

        Args:
            source_uri: Source file URI
            destination_uri: Destination file URI

        Returns:
            True if copy successful
        """
        pass

    @abstractmethod
    async def move(self, source_uri: str, destination_uri: str) -> bool:
        """
        Move/rename file within storage.

        Args:
            source_uri: Source file URI
            destination_uri: Destination file URI

        Returns:
            True if move successful
        """
        pass

    @abstractmethod
    async def get_upload_url(
        self,
        file_name: str,
        content_type: str = "application/octet-stream",
        expiration_seconds: int = 3600,
    ) -> dict[str, str]:
        """
        Generate presigned upload URL for client-side upload.

        Returns:
            Dictionary with 'url' and 'fields' (for form upload)
        """
        pass


# ============================================================================
# BASE IMPLEMENTATION (untuk shared logic)
# ============================================================================


class BaseFileStorageAdapter(FileStoragePort):
    """
    Base class dengan shared logic untuk semua file storage adapters.
    """

    def __init__(self):
        self._default_bucket: str | None = None
        self._integrity_check_enabled = True

    def _normalize_uri(self, file_uri: str) -> str:
        """Normalize file URI for consistent handling."""
        # Remove leading/trailing slashes
        return file_uri.strip("/")

    def _extract_key_from_uri(self, file_uri: str) -> str:
        """Extract object key from full URI."""
        # Format: s3://bucket/path/file.pdf or just path
        if file_uri.startswith("s3://"):
            parts = file_uri[5:].split("/", 1)
            if len(parts) > 1:
                return parts[1]
        return self._normalize_uri(file_uri)

    def _extract_bucket_from_uri(self, file_uri: str) -> str | None:
        """Extract bucket name from URI if present."""
        if file_uri.startswith("s3://"):
            parts = file_uri[5:].split("/", 1)
            if parts:
                return parts[0]
        return None

    async def _compute_checksum(self, content: bytes) -> str:
        """Compute SHA-256 checksum for integrity."""
        import hashlib

        return hashlib.sha256(content).hexdigest()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BaseFileStorageAdapter",
    "FileDownloadError",
    "FileNotFoundError",
    "FileStorageError",
    "FileStorageNotConfiguredError",
    "FileStoragePort",
    "FileUploadError",
]
