#!/usr/bin/env python3
"""
Module: local_file_storage.py
Layer: Adapters (Secondary)
Responsibility: Implementasi FileStoragePort menggunakan filesystem lokal (persistent).
Menyimpan file di disk dengan metadata dalam file JSON.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import logging
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

# Import port dari lokasi yang benar
from ports.primary.file_storage_port import (
    FileStoragePort,
    FileStorageStatus,
    StoredFile,
    UploadSession,
)

logger = logging.getLogger(__name__)


class LocalFileStorage(FileStoragePort):
    """
    Implementasi persistent file storage menggunakan filesystem lokal.
    Metadata disimpan dalam metadata.json, konten file di direktori yang sama.
    """

    def __init__(
        self,
        base_path: str = "./storage/files",
        max_file_size_mb: int = 100,
        default_expiry_days: int = 365,
    ):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.base_path / "metadata.json"
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._default_expiry_days = default_expiry_days
        self._lock = asyncio.Lock()
        self._running = False
        self._cleanup_task: asyncio.Task | None = None
        self._background_tasks: list[asyncio.Task] = []

        # In-memory cache untuk upload sessions (chunked)
        self._upload_sessions: dict[UUID, UploadSession] = {}
        self._chunk_storage: dict[tuple[UUID, int], bytes] = {}

        # Load metadata
        self._metadata: dict[str, dict] = {}  # key: str(file_id), value: dict metadata
        self._load_metadata()

    def _load_metadata(self):
        """Load metadata dari file JSON."""
        if self.metadata_path.exists():
            with open(self.metadata_path, "r") as f:
                self._metadata = json.load(f)
        else:
            self._metadata = {}

    def _save_metadata(self):
        """Simpan metadata ke file JSON."""
        with open(self.metadata_path, "w") as f:
            json.dump(self._metadata, f, default=str, indent=2)

    def _add_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.append(task)
        task.add_done_callback(
            lambda t: self._background_tasks.remove(t) if t in self._background_tasks else None
        )

    # ===================== HELPER =====================

    async def _log_audit(
        self, action: str, file_id: UUID | None, user_id: UUID, details: dict[str, Any]
    ):
        """Log audit ke console (bisa diganti dengan file log)."""
        print(f"[AUDIT] {action} on {file_id} by {user_id}: {details}")

    async def _compute_hashes(self, content: bytes) -> tuple[str, str]:
        sha256 = hashlib.sha256(content).hexdigest()
        md5 = hashlib.md5(content).hexdigest()
        return sha256, md5

    def _get_file_path(self, file_id: UUID, version: int | None = None) -> Path:
        """Dapatkan path file. Jika version None, gunakan versi terbaru (tanpa suffix)."""
        if version is not None:
            return self.base_path / f"{file_id}.v{version}"
        return self.base_path / str(file_id)

    def _get_latest_version(self, file_id: UUID) -> int:
        """Cari versi tertinggi dari file yang ada."""
        latest = 1
        base = self.base_path / str(file_id)
        if base.exists():
            return 1
        pattern = f"{file_id}.v*"
        for f in self.base_path.glob(pattern):
            try:
                ver = int(f.suffix[2:])
                if ver > latest:
                    latest = ver
            except ValueError:
                pass
        return latest if latest > 1 else 1

    def _get_all_versions(self, file_id: UUID) -> list[int]:
        versions = []
        base = self.base_path / str(file_id)
        if base.exists():
            versions.append(1)
        pattern = f"{file_id}.v*"
        for f in self.base_path.glob(pattern):
            try:
                ver = int(f.suffix[2:])
                if ver not in versions:
                    versions.append(ver)
            except ValueError:
                pass
        return sorted(versions)

    async def _read_file_content(self, path: Path) -> bytes:
        return await asyncio.to_thread(path.read_bytes)

    async def _write_file_content(self, path: Path, content: bytes):
        await asyncio.to_thread(path.write_bytes, content)

    async def _delete_file(self, path: Path):
        if path.exists():
            await asyncio.to_thread(path.unlink)

    def _stored_file_from_metadata(self, file_id: UUID, meta: dict) -> StoredFile:
        """Buat objek StoredFile dari metadata dict."""
        return StoredFile(
            id=UUID(meta["id"]),
            filename=meta["filename"],
            content=b"",  # konten tidak di-load
            content_type=meta["content_type"],
            size=meta["size"],
            hash_sha256=meta["hash_sha256"],
            hash_md5=meta["hash_md5"],
            status=FileStorageStatus(meta["status"]),
            version=meta["version"],
            original_filename=meta["original_filename"],
            metadata=meta["metadata"],
            uploaded_by=UUID(meta["uploaded_by"]),
            uploaded_at=datetime.fromisoformat(meta["uploaded_at"]),
            last_accessed_at=datetime.fromisoformat(meta["last_accessed_at"]) if meta.get("last_accessed_at") else None,
            access_count=meta["access_count"],
            expires_at=datetime.fromisoformat(meta["expires_at"]) if meta.get("expires_at") else None,
            storage_class=meta["storage_class"],
        )

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
            raise ValueError(f"File size exceeds limit {self._max_file_size_bytes}")

        sha256, md5 = await self._compute_hashes(content)

        if deduplicate:
            for file_id_str, meta in self._metadata.items():
                if meta["hash_sha256"] == sha256 and meta["status"] == "active":
                    existing_id = UUID(file_id_str)
                    await self._log_audit(
                        "UPLOAD_DEDUP",
                        existing_id,
                        uploaded_by,
                        {"original_file_id": file_id_str, "hash": sha256},
                    )
                    return f"file://{existing_id}"

        file_id = uuid4()
        if content_type is None:
            content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        expires_at = None
        if expiry_days:
            expires_at = datetime.now(UTC) + timedelta(days=expiry_days)
        elif self._default_expiry_days > 0:
            expires_at = datetime.now(UTC) + timedelta(days=self._default_expiry_days)

        file_path = self._get_file_path(file_id)
        await self._write_file_content(file_path, content)

        meta = {
            "id": str(file_id),
            "filename": str(file_id),
            "content_type": content_type,
            "size": len(content),
            "hash_sha256": sha256,
            "hash_md5": md5,
            "status": "active",
            "version": 1,
            "original_filename": file_name,
            "metadata": metadata or {},
            "uploaded_by": str(uploaded_by),
            "uploaded_at": datetime.now(UTC).isoformat(),
            "last_accessed_at": None,
            "access_count": 0,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "storage_class": "STANDARD",
        }
        async with self._lock:
            self._metadata[str(file_id)] = meta
            self._save_metadata()

        await self._log_audit(
            "UPLOAD",
            file_id,
            uploaded_by,
            {"filename": file_name, "size": len(content), "hash": sha256},
        )
        return f"file://{file_id}"

    # ===================== CHUNKED UPLOAD =====================

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
            raise ValueError(f"Total size exceeds limit {self._max_file_size_bytes}")

        session_id = uuid4()
        file_id = uuid4()

        session = UploadSession(
            id=session_id,
            file_id=file_id,
            total_chunks=total_chunks,
            received_chunks=set(),
            chunk_size=chunk_size,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

        meta = {
            "id": str(file_id),
            "filename": str(file_id),
            "content_type": content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            "size": total_size,
            "hash_sha256": "",
            "hash_md5": "",
            "status": "active",
            "version": 1,
            "original_filename": file_name,
            "metadata": metadata or {},
            "uploaded_by": str(uploaded_by),
            "uploaded_at": datetime.now(UTC).isoformat(),
            "last_accessed_at": None,
            "access_count": 0,
            "expires_at": None,
            "storage_class": "STANDARD",
        }
        async with self._lock:
            self._metadata[str(file_id)] = meta
            self._save_metadata()
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
            raise ValueError(f"Session {session_id} not found")
        if datetime.now(UTC) > session.expires_at:
            raise ValueError(f"Session {session_id} expired")
        if chunk_index in session.received_chunks:
            return len(session.received_chunks)

        self._chunk_storage[(session_id, chunk_index)] = chunk_data
        session.received_chunks.add(chunk_index)

        await self._log_audit(
            "UPLOAD_CHUNKED_PART",
            session.file_id,
            UUID(int=0),
            {"session_id": str(session_id), "chunk": chunk_index, "received": len(session.received_chunks)},
        )
        return len(session.received_chunks)

    async def upload_chunked_complete(self, session_id: UUID) -> str:
        session = self._upload_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
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
        sha256, md5 = await self._compute_hashes(full_content)

        for file_id_str, meta in self._metadata.items():
            if meta["hash_sha256"] == sha256 and meta["status"] == "active":
                async with self._lock:
                    del self._metadata[str(file_id)]
                    self._save_metadata()
                await self._log_audit(
                    "UPLOAD_DEDUP",
                    UUID(file_id_str),
                    UUID(meta["uploaded_by"]),
                    {"original_file_id": file_id_str},
                )
                return f"file://{UUID(file_id_str)}"

        file_path = self._get_file_path(file_id)
        await self._write_file_content(file_path, full_content)

        meta = self._metadata.get(str(file_id))
        if meta:
            meta["hash_sha256"] = sha256
            meta["hash_md5"] = md5
            meta["size"] = len(full_content)
            meta["uploaded_at"] = datetime.now(UTC).isoformat()
            async with self._lock:
                self._metadata[str(file_id)] = meta
                self._save_metadata()

        async with self._lock:
            del self._upload_sessions[session_id]
            keys = [k for k in self._chunk_storage if k[0] == session_id]
            for k in keys:
                del self._chunk_storage[k]

        await self._log_audit(
            "UPLOAD_CHUNKED_COMPLETE",
            file_id,
            UUID(meta["uploaded_by"]) if meta else UUID(int=0),
            {"total_size": len(full_content), "hash": sha256},
        )
        return f"file://{file_id}"

    # ===================== DOWNLOAD =====================

    async def download(self, file_uri: str) -> BinaryIO:
        file_id = self._parse_uri(file_uri)
        meta = self._metadata.get(str(file_id))
        if not meta or meta["status"] != "active":
            raise FileNotFoundError(f"File {file_id} not found or not active")

        file_path = self._get_file_path(file_id, version=meta.get("version", 1))
        if not file_path.exists():
            alt_path = self._get_file_path(file_id)
            if alt_path.exists():
                file_path = alt_path
            else:
                raise FileNotFoundError(f"File {file_id} missing on disk")

        content = await self._read_file_content(file_path)

        meta["last_accessed_at"] = datetime.now(UTC).isoformat()
        meta["access_count"] = meta.get("access_count", 0) + 1
        async with self._lock:
            self._metadata[str(file_id)] = meta
            self._save_metadata()

        await self._log_audit("DOWNLOAD", file_id, UUID(int=0), {"size": len(content)})
        return BytesIO(content)

    async def download_range(self, file_uri: str, start: int, end: int) -> bytes:
        stream = await self.download(file_uri)
        stream.seek(start)
        length = end - start + 1
        return stream.read(length)

    # ===================== DELETE =====================

    async def delete(self, file_uri: str, soft_delete: bool = True) -> bool:
        file_id = self._parse_uri(file_uri)
        meta = self._metadata.get(str(file_id))
        if not meta:
            return False

        if soft_delete:
            meta["status"] = "deleted"
            async with self._lock:
                self._metadata[str(file_id)] = meta
                self._save_metadata()
            await self._log_audit("SOFT_DELETE", file_id, UUID(int=0), {})
        else:
            file_path = self._get_file_path(file_id)
            await self._delete_file(file_path)
            for ver in self._get_all_versions(file_id):
                vpath = self._get_file_path(file_id, version=ver)
                await self._delete_file(vpath)
            async with self._lock:
                del self._metadata[str(file_id)]
                self._save_metadata()
            await self._log_audit("HARD_DELETE", file_id, UUID(int=0), {})
        return True

    # ===================== METADATA =====================

    async def get_metadata(self, file_uri: str) -> dict[str, Any]:
        file_id = self._parse_uri(file_uri)
        meta = self._metadata.get(str(file_id))
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        stored = self._stored_file_from_metadata(file_id, meta)
        return stored.to_dict()

    async def update_metadata(
        self, file_uri: str, metadata: dict[str, Any], updated_by: UUID
    ) -> bool:
        file_id = self._parse_uri(file_uri)
        meta = self._metadata.get(str(file_id))
        if not meta:
            return False
        meta["metadata"].update(metadata)
        async with self._lock:
            self._metadata[str(file_id)] = meta
            self._save_metadata()
        await self._log_audit(
            "UPDATE_METADATA",
            file_id,
            updated_by,
            {"metadata_keys": list(metadata.keys())},
        )
        return True

    # ===================== PRESIGNED URL =====================

    async def generate_presigned_url(
        self, file_uri: str, expiration_seconds: int = 3600, operation: str = "GET"
    ) -> str:
        file_id = self._parse_uri(file_uri)
        meta = self._metadata.get(str(file_id))
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")

        token_seed = f"{file_id}_{expiration_seconds}_{int(time.time())}_{operation}"
        token = hashlib.sha256(token_seed.encode()).hexdigest()[:32]
        expires_at = datetime.now(UTC) + timedelta(seconds=expiration_seconds)
        presigned_url = (
            f"http://storage.internal/files/{file_id}"
            f"?token={token}&expires={int(expires_at.timestamp())}&op={operation}"
        )
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
        file_id = self._parse_uri(file_uri)
        old_meta = self._metadata.get(str(file_id))
        if not old_meta:
            raise FileNotFoundError(f"File {file_id} not found")

        content = new_content.read()
        sha256, md5 = await self._compute_hashes(content)

        current_version = old_meta.get("version", 1)
        new_version = current_version + 1

        old_file_path = self._get_file_path(file_id, version=None)
        if old_file_path.exists():
            old_version_path = self._get_file_path(file_id, version=current_version)
            await asyncio.to_thread(shutil.move, old_file_path, old_version_path)

        new_file_path = self._get_file_path(file_id)
        await self._write_file_content(new_file_path, content)

        old_meta["version"] = new_version
        old_meta["hash_sha256"] = sha256
        old_meta["hash_md5"] = md5
        old_meta["size"] = len(content)
        old_meta["uploaded_by"] = str(uploaded_by)
        old_meta["uploaded_at"] = datetime.now(UTC).isoformat()
        async with self._lock:
            self._metadata[str(file_id)] = old_meta
            self._save_metadata()

        await self._log_audit(
            "VERSION_CREATED",
            file_id,
            uploaded_by,
            {"previous_version": current_version, "new_version": new_version},
        )
        return f"file://{file_id}"

    async def get_versions(self, file_uri: str) -> list[dict[str, Any]]:
        file_id = self._parse_uri(file_uri)
        original_filename = self._metadata.get(str(file_id), {}).get("original_filename")
        if not original_filename:
            raise FileNotFoundError(f"File {file_id} not found")

        versions = []
        for meta in self._metadata.values():
            if meta.get("original_filename") == original_filename:
                stored = self._stored_file_from_metadata(UUID(meta["id"]), meta)
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
        for file_id_str, meta in self._metadata.items():
            expires_at = meta.get("expires_at")
            if expires_at and meta["status"] == "active":
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt <= now:
                    meta["status"] = "deleted"
                    to_delete.append(file_id_str)
        if to_delete:
            async with self._lock:
                self._save_metadata()
            for fid in to_delete:
                await self._log_audit("EXPIRED_DELETE", UUID(fid), UUID(int=0), {})
            print(f"Cleaned up {len(to_delete)} expired files")

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
        for meta in self._metadata.values():
            if uploaded_by and UUID(meta["uploaded_by"]) != uploaded_by:
                continue
            if status and meta["status"] != status.value:
                continue
            stored = self._stored_file_from_metadata(UUID(meta["id"]), meta)
            result.append(stored.to_dict())
        return result[offset : offset + limit]

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        # Untuk sementara return list kosong (bisa dikembangkan)
        return []

    async def get_statistics(self) -> dict[str, Any]:
        total_files = len(self._metadata)
        total_size = 0
        active = 0
        deleted = 0
        for meta in self._metadata.values():
            total_size += meta.get("size", 0)
            if meta["status"] == "active":
                active += 1
            elif meta["status"] == "deleted":
                deleted += 1
        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "active_files": active,
            "deleted_files": deleted,
            "dedup_saved_bytes": 0,
            "upload_sessions_active": len(self._upload_sessions),
            "audit_log_size": 0,
        }

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_files": len(self._metadata),
            "cleanup_running": self._running,
            "max_file_size_mb": self._max_file_size_bytes // (1024 * 1024),
            "base_path": str(self.base_path),
        }

    # ===================== UTILITY =====================

    def _parse_uri(self, file_uri: str) -> UUID:
        if not file_uri.startswith("file://"):
            raise ValueError("Invalid file URI format, expected file://<uuid>")
        file_id_str = file_uri[7:]
        try:
            return UUID(file_id_str)
        except ValueError:
            raise ValueError(f"Invalid file UUID: {file_id_str}")


__all__ = ["LocalFileStorage"]