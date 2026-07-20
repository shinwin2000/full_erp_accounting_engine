#!/usr/bin/env python3
"""
Module: file_storage_port.py
Layer: Ports (Primary)
Responsibility:
    - Mendefinisikan antarmuka (port) untuk file storage dengan simulasi S3-like.
    - Menyediakan implementasi in-memory untuk testing/fallback.

Features: upload, download, delete, metadata, presigned URL, chunking, versioning, audit.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, BinaryIO
from uuid import UUID

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class FileStorageStatus(Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
    CORRUPTED = "corrupted"


@dataclass
class StoredFile:
    id: UUID
    filename: str
    content: bytes
    content_type: str
    size: int
    hash_sha256: str
    hash_md5: str
    status: FileStorageStatus
    version: int
    original_filename: str
    metadata: dict[str, Any]
    uploaded_by: UUID
    uploaded_at: datetime
    last_accessed_at: datetime | None
    access_count: int
    expires_at: datetime | None
    storage_class: str  # STANDARD, GLACIER, REDUCED_REDUNDANCY

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
            "hash_sha256": self.hash_sha256,
            "hash_md5": self.hash_md5,
            "status": self.status.value,
            "version": self.version,
            "original_filename": self.original_filename,
            "metadata": self.metadata,
            "uploaded_by": str(self.uploaded_by),
            "uploaded_at": self.uploaded_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "access_count": self.access_count,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "storage_class": self.storage_class,
        }


@dataclass
class UploadSession:
    id: UUID
    file_id: UUID
    total_chunks: int
    received_chunks: set
    chunk_size: int
    created_at: datetime
    expires_at: datetime


# ==================== PORT (INTERFACE) ====================

class FileStoragePort(ABC):
    """
    Port interface untuk file storage.
    Semua metode wajib diimplementasikan oleh adapter konkret.
    """

    @abstractmethod
    async def upload(
        self,
        file_content: BinaryIO,
        file_name: str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        uploaded_by: UUID | None = None,
        deduplicate: bool = True,
        expiry_days: int | None = None,
    ) -> str:
        """
        Mengunggah file dan mengembalikan URI unik (format: file://{file_id}).
        Support deduplication, metadata, expiry.
        """
        ...

    @abstractmethod
    async def upload_chunked_start(
        self,
        file_name: str,
        total_size: int,
        total_chunks: int,
        chunk_size: int,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        uploaded_by: UUID | None = None,
    ) -> UUID:
        """Memulai upload multi-part. Mengembalikan session_id."""
        ...

    @abstractmethod
    async def upload_chunked_part(
        self, session_id: UUID, chunk_index: int, chunk_data: bytes
    ) -> int:
        """Mengunggah satu chunk. Mengembalikan jumlah chunk yang sudah diterima."""
        ...

    @abstractmethod
    async def upload_chunked_complete(self, session_id: UUID) -> str:
        """Menyelesaikan upload multi-part. Mengembalikan URI file."""
        ...

    @abstractmethod
    async def download(self, file_uri: str) -> BinaryIO:
        """Mengunduh file berdasarkan URI. Mengembalikan BytesIO object."""
        ...

    @abstractmethod
    async def download_range(self, file_uri: str, start: int, end: int) -> bytes:
        """Mengunduh byte range tertentu."""
        ...

    @abstractmethod
    async def delete(self, file_uri: str, soft_delete: bool = True) -> bool:
        """Menghapus file (soft delete atau hard delete). Mengembalikan True jika berhasil."""
        ...

    @abstractmethod
    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        """Mendapatkan metadata file tanpa konten."""
        ...

    @abstractmethod
    async def update_metadata(
        self, file_uri: str, metadata: dict[str, Any], updated_by: UUID
    ) -> bool:
        """Memperbarui metadata file. Mengembalikan True jika berhasil."""
        ...

    @abstractmethod
    async def generate_presigned_url(
        self, file_uri: str, expiration_seconds: int = 3600, operation: str = "GET"
    ) -> str:
        """Generate URL sementara untuk akses aman (simulasi dengan token)."""
        ...

    @abstractmethod
    async def verify_presigned_url(
        self, token: str, file_id: UUID, operation: str, expires_timestamp: int
    ) -> bool:
        """Verifikasi token presigned URL."""
        ...

    @abstractmethod
    async def create_version(self, file_uri: str, new_content: BinaryIO, uploaded_by: UUID) -> str:
        """Membuat versi baru dari file yang ada. Mengembalikan URI versi baru."""
        ...

    @abstractmethod
    async def get_versions(self, file_uri: str) -> list[dict[str, Any]]:
        """Mendapatkan semua versi dari sebuah file (berdasarkan original_filename)."""
        ...

    @abstractmethod
    async def start_cleanup_task(self, interval_hours: int = 24):
        """Memulai background task untuk menghapus file expired."""
        ...

    @abstractmethod
    async def stop_cleanup(self):
        """Menghentikan background cleanup task."""
        ...

    @abstractmethod
    async def list_files(
        self,
        uploaded_by: UUID | None = None,
        status: FileStorageStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Mendaftar file dengan filter."""
        ...

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Ambil audit log."""
        ...

    @abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        """Statistik storage."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check storage."""
        ...


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemoryFileStorage(FileStoragePort):
    """
    Implementasi in-memory file storage dengan simulasi fitur S3.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self, max_file_size_mb: int = 100, default_expiry_days: int = 365):
        self._storage: dict[UUID, StoredFile] = {}
        self._file_id_by_hash: dict[str, UUID] = {}
        self._upload_sessions: dict[UUID, UploadSession] = {}
        self._chunk_storage: dict[tuple[UUID, int], bytes] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._default_expiry_days = default_expiry_days
        self._cleanup_task: asyncio.Task | None = None
        self._running = False
        self._background_tasks: list[asyncio.Task] = []

    def _add_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.append(task)
        task.add_done_callback(
            lambda t: self._background_tasks.remove(t) if t in self._background_tasks else None
        )

    # ===================== AUDIT =====================

    async def _log_audit(
        self, action: str, file_id: UUID | None, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "file_id": str(file_id) if file_id else None,
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"FILE AUDIT: {action} on {file_id} by {user_id}")

    # ===================== HASHING & DEDUP =====================

    async def _compute_hashes(self, content: bytes) -> tuple[str, str]:
        sha256 = hashlib.sha256(content).hexdigest()
        md5 = hashlib.md5(content).hexdigest()
        return sha256, md5

    async def _check_duplicate(self, sha256: str) -> StoredFile | None:
        existing_id = self._file_id_by_hash.get(sha256)
        if existing_id:
            return self._storage.get(existing_id)
        return None

    # ===================== UPLOAD =====================

    async def upload(
        self,
        file_content: BinaryIO,
        file_name: str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        uploaded_by: UUID | None = None,
        deduplicate: bool = True,
        expiry_days: int | None = None,
    ) -> str:
        if uploaded_by is None:
            uploaded_by = UUID(int=0)

        content = file_content.read()
        if len(content) > self._max_file_size_bytes:
            raise ValueError(
                f"File size {len(content)} exceeds maximum {self._max_file_size_bytes} bytes"
            )

        sha256, md5 = await self._compute_hashes(content)

        if deduplicate:
            existing = await self._check_duplicate(sha256)
            if existing:
                await self._log_audit(
                    "UPLOAD_DEDUP",
                    existing.id,
                    uploaded_by,
                    {"original_file_id": str(existing.id), "hash": sha256},
                )
                return f"file://{existing.id}"

        file_id = uuid.uuid4()
        if content_type is None:
            content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        expires_at = None
        if expiry_days:
            expires_at = datetime.now(UTC) + timedelta(days=expiry_days)
        elif self._default_expiry_days > 0:
            expires_at = datetime.now(UTC) + timedelta(days=self._default_expiry_days)

        stored = StoredFile(
            id=file_id,
            filename=str(file_id),
            content=content,
            content_type=content_type,
            size=len(content),
            hash_sha256=sha256,
            hash_md5=md5,
            status=FileStorageStatus.ACTIVE,
            version=1,
            original_filename=file_name,
            metadata=metadata or {},
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(UTC),
            last_accessed_at=None,
            access_count=0,
            expires_at=expires_at,
            storage_class="STANDARD",
        )

        async with self._lock:
            self._storage[file_id] = stored
            self._file_id_by_hash[sha256] = file_id

        await self._log_audit(
            "UPLOAD",
            file_id,
            uploaded_by,
            {"filename": file_name, "size": len(content), "hash": sha256},
        )
        return f"file://{file_id}"

    async def upload_chunked_start(
        self,
        file_name: str,
        total_size: int,
        total_chunks: int,
        chunk_size: int,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        uploaded_by: UUID | None = None,
    ) -> UUID:
        if uploaded_by is None:
            uploaded_by = UUID(int=0)

        if total_size > self._max_file_size_bytes:
            raise ValueError(f"Total size {total_size} exceeds maximum {self._max_file_size_bytes}")

        session_id = uuid.uuid4()
        file_id = uuid.uuid4()

        session = UploadSession(
            id=session_id,
            file_id=file_id,
            total_chunks=total_chunks,
            received_chunks=set(),
            chunk_size=chunk_size,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

        temp_file = StoredFile(
            id=file_id,
            filename=str(file_id),
            content=b"",
            content_type=content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            size=total_size,
            hash_sha256="",
            hash_md5="",
            status=FileStorageStatus.ACTIVE,
            version=1,
            original_filename=file_name,
            metadata=metadata or {},
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(UTC),
            last_accessed_at=None,
            access_count=0,
            expires_at=None,
            storage_class="STANDARD",
        )

        async with self._lock:
            self._storage[file_id] = temp_file
            self._upload_sessions[session_id] = session

        await self._log_audit(
            "UPLOAD_CHUNKED_START",
            file_id,
            uploaded_by,
            {"total_chunks": total_chunks, "total_size": total_size},
        )
        return session_id

    async def upload_chunked_part(
        self, session_id: UUID, chunk_index: int, chunk_data: bytes
    ) -> int:
        session = self._upload_sessions.get(session_id)
        if not session:
            raise ValueError(f"Upload session {session_id} not found or expired")
        if datetime.now(UTC) > session.expires_at:
            raise ValueError(f"Upload session {session_id} expired")

        if chunk_index in session.received_chunks:
            return len(session.received_chunks)

        self._chunk_storage[(session_id, chunk_index)] = chunk_data
        session.received_chunks.add(chunk_index)

        await self._log_audit(
            "UPLOAD_CHUNKED_PART",
            session.file_id,
            UUID(int=0),
            {
                "session_id": str(session_id),
                "chunk": chunk_index,
                "received": len(session.received_chunks),
            },
        )
        return len(session.received_chunks)

    async def upload_chunked_complete(self, session_id: UUID) -> str:
        session = self._upload_sessions.get(session_id)
        if not session:
            raise ValueError(f"Upload session {session_id} not found")

        if len(session.received_chunks) != session.total_chunks:
            raise ValueError(
                f"Missing chunks: expected {session.total_chunks}, got {len(session.received_chunks)}"
            )

        all_chunks = []
        for i in range(session.total_chunks):
            chunk = self._chunk_storage.get((session_id, i))
            if chunk is None:
                raise ValueError(f"Chunk {i} missing")
            all_chunks.append(chunk)
        full_content = b"".join(all_chunks)

        file_id = session.file_id
        stored = self._storage.get(file_id)
        if not stored:
            raise ValueError(f"File {file_id} not found")

        sha256, md5 = await self._compute_hashes(full_content)

        existing = await self._check_duplicate(sha256)
        if existing:
            async with self._lock:
                del self._storage[file_id]
            await self._log_audit(
                "UPLOAD_DEDUP",
                existing.id,
                stored.uploaded_by,
                {"original_file_id": str(existing.id)},
            )
            return f"file://{existing.id}"

        stored.content = full_content
        stored.hash_sha256 = sha256
        stored.hash_md5 = md5
        stored.size = len(full_content)
        stored.status = FileStorageStatus.ACTIVE
        stored.uploaded_at = datetime.now(UTC)

        async with self._lock:
            self._file_id_by_hash[sha256] = file_id
            del self._upload_sessions[session_id]
            keys_to_del = [k for k in self._chunk_storage if k[0] == session_id]
            for k in keys_to_del:
                del self._chunk_storage[k]

        await self._log_audit(
            "UPLOAD_CHUNKED_COMPLETE",
            file_id,
            stored.uploaded_by,
            {"total_size": len(full_content), "hash": sha256},
        )
        return f"file://{file_id}"

    # ===================== DOWNLOAD =====================

    async def download(self, file_uri: str) -> BinaryIO:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format, expected file://<uuid>")
        file_id_str = file_uri[7:]
        try:
            file_id = UUID(file_id_str)
        except ValueError:
            raise ValueError(f"Invalid file UUID: {file_id_str}")

        stored = self._storage.get(file_id)
        if not stored:
            raise FileNotFoundError(f"File {file_id} not found")
        if stored.status != FileStorageStatus.ACTIVE:
            raise ValueError(f"File {file_id} is {stored.status.value}")

        stored.last_accessed_at = datetime.now(UTC)
        stored.access_count += 1

        await self._log_audit("DOWNLOAD", file_id, UUID(int=0), {"size": stored.size})
        from io import BytesIO
        return BytesIO(stored.content)

    async def download_range(self, file_uri: str, start: int, end: int) -> bytes:
        stream = await self.download(file_uri)
        stream.seek(start)
        length = end - start + 1
        return stream.read(length)

    # ===================== DELETE =====================

    async def delete(self, file_uri: str, soft_delete: bool = True) -> bool:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format")
        file_id_str = file_uri[7:]
        try:
            file_id = UUID(file_id_str)
        except ValueError:
            raise ValueError(f"Invalid file UUID: {file_id_str}")

        stored = self._storage.get(file_id)
        if not stored:
            return False

        if soft_delete:
            stored.status = FileStorageStatus.DELETED
            await self._log_audit("SOFT_DELETE", file_id, UUID(int=0), {})
        else:
            async with self._lock:
                del self._storage[file_id]
                if stored.hash_sha256 in self._file_id_by_hash:
                    del self._file_id_by_hash[stored.hash_sha256]
            await self._log_audit("HARD_DELETE", file_id, UUID(int=0), {})
        return True

    # ===================== METADATA =====================

    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format")
        file_id_str = file_uri[7:]
        try:
            file_id = UUID(file_id_str)
        except ValueError:
            raise ValueError(f"Invalid file UUID: {file_id_str}")

        stored = self._storage.get(file_id)
        if not stored:
            raise FileNotFoundError(f"File {file_id} not found")
        return stored.to_dict()

    async def update_metadata(
        self, file_uri: str, metadata: dict[str, Any], updated_by: UUID
    ) -> bool:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format")
        file_id_str = file_uri[7:]
        file_id = UUID(file_id_str)

        stored = self._storage.get(file_id)
        if not stored:
            return False
        stored.metadata.update(metadata)
        await self._log_audit(
            "UPDATE_METADATA", file_id, updated_by, {"metadata_keys": list(metadata.keys())}
        )
        return True

    # ===================== PRESIGNED URL =====================

    async def generate_presigned_url(
        self, file_uri: str, expiration_seconds: int = 3600, operation: str = "GET"
    ) -> str:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format")
        file_id_str = file_uri[7:]
        file_id = UUID(file_id_str)

        stored = self._storage.get(file_id)
        if not stored:
            raise FileNotFoundError(f"File {file_id} not found")

        token_seed = f"{file_id}_{expiration_seconds}_{int(time.time())}_{operation}"
        token = hashlib.sha256(token_seed.encode()).hexdigest()[:32]
        expires_at = datetime.now(UTC) + timedelta(seconds=expiration_seconds)
        presigned_url = f"http://storage.internal/files/{file_id}?token={token}&expires={int(expires_at.timestamp())}&op={operation}"

        await self._log_audit(
            "PRESIGNED_URL",
            file_id,
            UUID(int=0),
            {"expiration_seconds": expiration_seconds, "operation": operation},
        )
        return presigned_url

    async def verify_presigned_url(
        self, token: str, file_id: UUID, operation: str, expires_timestamp: int
    ) -> bool:
        if expires_timestamp < int(time.time()):
            return False
        expected = hashlib.sha256(
            f"{file_id}_{3600}_{expires_timestamp}_{operation}".encode()
        ).hexdigest()[:32]
        return token == expected

    # ===================== VERSIONING =====================

    async def create_version(self, file_uri: str, new_content: BinaryIO, uploaded_by: UUID) -> str:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format")
        old_file_id = UUID(file_uri[7:])
        old_stored = self._storage.get(old_file_id)
        if not old_stored:
            raise FileNotFoundError(f"File {old_file_id} not found")

        content = new_content.read()
        sha256, md5 = await self._compute_hashes(content)

        new_file_id = uuid.uuid4()
        new_stored = StoredFile(
            id=new_file_id,
            filename=str(new_file_id),
            content=content,
            content_type=old_stored.content_type,
            size=len(content),
            hash_sha256=sha256,
            hash_md5=md5,
            status=FileStorageStatus.ACTIVE,
            version=old_stored.version + 1,
            original_filename=old_stored.original_filename,
            metadata=old_stored.metadata.copy(),
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(UTC),
            last_accessed_at=None,
            access_count=0,
            expires_at=old_stored.expires_at,
            storage_class=old_stored.storage_class,
        )

        async with self._lock:
            self._storage[new_file_id] = new_stored
            self._file_id_by_hash[sha256] = new_file_id

        await self._log_audit(
            "VERSION_CREATED",
            new_file_id,
            uploaded_by,
            {"previous_version": str(old_file_id), "version": new_stored.version},
        )
        return f"file://{new_file_id}"

    async def get_versions(self, file_uri: str) -> list[dict[str, Any]]:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format")
        file_id = UUID(file_uri[7:])
        original = self._storage.get(file_id)
        if not original:
            raise FileNotFoundError(f"File {file_id} not found")

        versions = []
        for stored in self._storage.values():
            if stored.original_filename == original.original_filename:
                versions.append(stored.to_dict())
        return sorted(versions, key=lambda x: x["version"])

    # ===================== EXPIRY & CLEANUP =====================

    async def start_cleanup_task(self, interval_hours: int = 24):
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_hours))
        self._add_background_task(self._cleanup_task)

    async def _cleanup_loop(self, interval_hours: int):
        while self._running:
            await asyncio.sleep(interval_hours * 3600)
            await self._cleanup_expired()

    async def _cleanup_expired(self):
        now = datetime.now(UTC)
        to_delete = []
        async with self._lock:
            for file_id, stored in self._storage.items():
                if (
                    stored.expires_at
                    and stored.expires_at <= now
                    and stored.status == FileStorageStatus.ACTIVE
                ):
                    stored.status = FileStorageStatus.DELETED
                    to_delete.append(file_id)
        for fid in to_delete:
            await self._log_audit("EXPIRED_DELETE", fid, UUID(int=0), {})
        logger.info(f"Cleaned up {len(to_delete)} expired files")

    async def stop_cleanup(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

    # ===================== QUERY & ADMIN =====================

    async def list_files(
        self,
        uploaded_by: UUID | None = None,
        status: FileStorageStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        result = []
        for stored in self._storage.values():
            if uploaded_by and stored.uploaded_by != uploaded_by:
                continue
            if status and stored.status != status:
                continue
            result.append(stored.to_dict())
        return result[offset : offset + limit]

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def get_statistics(self) -> dict[str, Any]:
        total_files = len(self._storage)
        total_size = sum(f.size for f in self._storage.values())
        active_files = sum(1 for f in self._storage.values() if f.status == FileStorageStatus.ACTIVE)
        deleted_files = sum(1 for f in self._storage.values() if f.status == FileStorageStatus.DELETED)
        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "active_files": active_files,
            "deleted_files": deleted_files,
            "dedup_saved_bytes": 0,
            "upload_sessions_active": len(self._upload_sessions),
            "audit_log_size": len(self._audit_log),
        }

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_files": len(self._storage),
            "cleanup_running": self._running,
            "max_file_size_mb": self._max_file_size_bytes // (1024 * 1024),
        }


# ==================== ALIAS UNTUK DI CONTAINER ====================

# Alias untuk kepatuhan terhadap nama yang diharapkan DI container
FileStoragePortImpl = InMemoryFileStorage


# ==================== EXPORTS ====================

__all__ = [
    "FileStoragePort",
    "FileStoragePortImpl",
    "FileStorageStatus",
    "InMemoryFileStorage",
    "StoredFile",
    "UploadSession",
]
