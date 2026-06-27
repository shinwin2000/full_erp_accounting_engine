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

    # ===== Additional methods from concrete port (file_storage_port.py) =====
    @abstractmethod
    async def create_version(self, file_uri: str) -> dict[str, Any]:
        """Create a new version of a file."""
        pass

    @abstractmethod
    async def download_range(self, file_uri: str, start: int, end: int) -> BinaryIO:
        """Download a byte range of a file."""
        pass

    @abstractmethod
    async def get_audit_log(self, file_uri: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get audit log for file operations."""
        pass

    @abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        """Get storage statistics."""
        pass

    @abstractmethod
    async def get_versions(self, file_uri: str) -> list[dict[str, Any]]:
        """Get all versions of a file."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check storage health."""
        pass

    @abstractmethod
    async def start_cleanup_task(self) -> dict[str, Any]:
        """Start the cleanup task."""
        pass

    @abstractmethod
    async def stop_cleanup(self) -> dict[str, Any]:
        """Stop the cleanup task."""
        pass

    @abstractmethod
    async def update_metadata(self, file_uri: str, metadata: dict[str, str]) -> dict[str, Any]:
        """Update file metadata."""
        pass

    @abstractmethod
    async def upload_chunked_start(self, file_name: str, total_size: int) -> dict[str, Any]:
        """Start a chunked upload."""
        pass

    @abstractmethod
    async def upload_chunked_part(self, upload_id: str, part_number: int, data: bytes) -> dict[str, Any]:
        """Upload a part of a chunked upload."""
        pass

    @abstractmethod
    async def upload_chunked_complete(self, upload_id: str) -> dict[str, Any]:
        """Complete a chunked upload."""
        pass

    @abstractmethod
    async def verify_presigned_url(self, url: str) -> bool:
        """Verify a presigned URL."""
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

    # ===== Implementasi method yang hilang sebagai stub =====
    # Method ini akan di-override oleh subclass konkret

    async def upload(
        self,
        file_content: BinaryIO,
        file_name: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        bucket: str | None = None,
    ) -> str:
        raise NotImplementedError("Subclass must implement upload")

    async def download(self, file_uri: str) -> BinaryIO:
        raise NotImplementedError("Subclass must implement download")

    async def delete(self, file_uri: str) -> bool:
        raise NotImplementedError("Subclass must implement delete")

    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement get_metadata")

    async def exists(self, file_uri: str) -> bool:
        raise NotImplementedError("Subclass must implement exists")

    async def generate_presigned_url(self, file_uri: str, expiration_seconds: int = 3600) -> str:
        raise NotImplementedError("Subclass must implement generate_presigned_url")

    async def list_files(self, prefix: str = "", limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError("Subclass must implement list_files")

    async def get_size(self, file_uri: str) -> int:
        raise NotImplementedError("Subclass must implement get_size")

    async def copy(self, source_uri: str, destination_uri: str) -> bool:
        raise NotImplementedError("Subclass must implement copy")

    async def move(self, source_uri: str, destination_uri: str) -> bool:
        raise NotImplementedError("Subclass must implement move")

    async def get_upload_url(
        self,
        file_name: str,
        content_type: str = "application/octet-stream",
        expiration_seconds: int = 3600,
    ) -> dict[str, str]:
        raise NotImplementedError("Subclass must implement get_upload_url")

    # ===== Additional methods (stub) =====
    async def create_version(self, file_uri: str) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement create_version")

    async def download_range(self, file_uri: str, start: int, end: int) -> BinaryIO:
        raise NotImplementedError("Subclass must implement download_range")

    async def get_audit_log(self, file_uri: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError("Subclass must implement get_audit_log")

    async def get_statistics(self) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement get_statistics")

    async def get_versions(self, file_uri: str) -> list[dict[str, Any]]:
        raise NotImplementedError("Subclass must implement get_versions")

    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement health_check")

    async def start_cleanup_task(self) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement start_cleanup_task")

    # ===== TAMBAHAN: stop_cleanup =====
    async def stop_cleanup(self) -> dict[str, Any]:
        """
        Stop the cleanup task.
        Base implementation - override in subclass.
        """
        return {"status": "not_implemented", "message": "stop_cleanup not implemented in base adapter"}

    async def update_metadata(self, file_uri: str, metadata: dict[str, str]) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement update_metadata")

    async def upload_chunked_start(self, file_name: str, total_size: int) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement upload_chunked_start")

    async def upload_chunked_part(self, upload_id: str, part_number: int, data: bytes) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement upload_chunked_part")

    async def upload_chunked_complete(self, upload_id: str) -> dict[str, Any]:
        raise NotImplementedError("Subclass must implement upload_chunked_complete")

    async def verify_presigned_url(self, url: str) -> bool:
        raise NotImplementedError("Subclass must implement verify_presigned_url")


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
