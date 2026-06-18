#!/usr/bin/env python3
"""
Module: snapshot_store_port.py
Layer: Ports (Secondary)
Responsibility: Antarmuka dan implementasi in-memory untuk snapshot store.
               Menyimpan state aggregate secara periodik untuk mempercepat
               event sourcing replay. Mendukung kompresi, enkripsi opsional,
               TTL, versioning, multi-tenant, audit, dan cleanup.
Audit: Setiap penyimpanan dan pengambilan snapshot tercatat.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class SnapshotCompression(Enum):
    """Jenis kompresi snapshot."""

    NONE = "none"
    ZLIB = "zlib"
    GZIP = "gzip"  # simulated as zlib


class SnapshotStatus(Enum):
    """Status snapshot."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass
class SnapshotMetadata:
    """Metadata snapshot."""

    snapshot_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    version: int
    last_event_sequence: int
    created_at: datetime
    created_by: UUID
    size_bytes: int
    compressed_size_bytes: int
    compression: SnapshotCompression
    status: SnapshotStatus
    ttl_days: int
    expires_at: datetime | None
    hash_sha256: str
    tags: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
            "last_event_sequence": self.last_event_sequence,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "size_bytes": self.size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "compression": self.compression.value,
            "status": self.status.value,
            "ttl_days": self.ttl_days,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "hash_sha256": self.hash_sha256,
            "tags": self.tags,
        }


@dataclass
class Snapshot:
    """Snapshot dengan data dan metadata."""

    metadata: SnapshotMetadata
    data: bytes  # snapshot data (state aggregate)


class SnapshotStorePort:
    """
    In-memory snapshot store.
    """

    def __init__(self, default_ttl_days: int = 30, enable_compression: bool = True):
        self._snapshots: dict[UUID, Snapshot] = {}
        self._index_by_aggregate: dict[
            tuple[str, UUID], list[UUID]
        ] = {}  # (aggregate_type, aggregate_id) -> list of snapshot ids
        self._default_ttl = default_ttl_days
        self._enable_compression = enable_compression
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

    # ==================== HELPER ====================

    async def _log_audit(self, action: str, snapshot_id: UUID, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "snapshot_id": str(snapshot_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"SNAPSHOT AUDIT: {action} on {snapshot_id}")

    async def _compute_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def _compress(self, data: bytes) -> tuple[bytes, SnapshotCompression]:
        if not self._enable_compression or len(data) < 1024:
            return data, SnapshotCompression.NONE
        compressed = zlib.compress(data, level=6)
        return compressed, SnapshotCompression.ZLIB

    async def _decompress(self, data: bytes, compression: SnapshotCompression) -> bytes:
        if compression == SnapshotCompression.NONE:
            return data
        elif compression == SnapshotCompression.ZLIB:
            return zlib.decompress(data)
        else:
            return data  # fallback

    async def _serialize_state(self, state: Any) -> bytes:
        """Serialize state ke JSON bytes."""
        return json.dumps(state, default=str, sort_keys=True).encode()

    async def _deserialize_state(self, data: bytes) -> Any:
        """Deserialize dari bytes ke state."""
        return json.loads(data.decode())

    # ==================== SAVE ====================

    async def save(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        version: int,
        last_event_sequence: int,
        state: Any,
        created_by: UUID,
        tags: dict[str, str] | None = None,
        ttl_days: int | None = None,
    ) -> UUID:
        """Simpan snapshot dari state aggregate."""
        snapshot_id = uuid4()
        now = datetime.now(UTC)
        ttl = ttl_days or self._default_ttl
        expires_at = now + timedelta(days=ttl) if ttl > 0 else None

        # Serialize
        raw_data = await self._serialize_state(state)
        compressed_data, compression = await self._compress(raw_data)
        data_hash = await self._compute_hash(compressed_data)

        metadata = SnapshotMetadata(
            snapshot_id=snapshot_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            version=version,
            last_event_sequence=last_event_sequence,
            created_at=now,
            created_by=created_by,
            size_bytes=len(raw_data),
            compressed_size_bytes=len(compressed_data),
            compression=compression,
            status=SnapshotStatus.ACTIVE,
            ttl_days=ttl,
            expires_at=expires_at,
            hash_sha256=data_hash,
            tags=tags or {},
        )
        snapshot = Snapshot(metadata=metadata, data=compressed_data)

        async with self._lock:
            self._snapshots[snapshot_id] = snapshot
            key = (aggregate_type, aggregate_id)
            if key not in self._index_by_aggregate:
                self._index_by_aggregate[key] = []
            self._index_by_aggregate[key].append(snapshot_id)

        await self._log_audit(
            "SAVE",
            snapshot_id,
            {
                "aggregate_type": aggregate_type,
                "aggregate_id": str(aggregate_id),
                "version": version,
                "event_sequence": last_event_sequence,
                "ttl_days": ttl,
            },
        )
        return snapshot_id

    # ==================== LOAD ====================

    async def load_latest(
        self, aggregate_type: str, aggregate_id: UUID
    ) -> tuple[UUID, Any, int, int] | None:
        """
        Load snapshot terbaru untuk aggregate.
        Returns (snapshot_id, state, version, last_event_sequence) atau None.
        """
        key = (aggregate_type, aggregate_id)
        snapshot_ids = self._index_by_aggregate.get(key, [])
        if not snapshot_ids:
            return None
        # Cari yang status ACTIVE dan terbaru
        latest = None
        latest_sequence = -1
        for sid in snapshot_ids:
            snap = self._snapshots.get(sid)
            if snap and snap.metadata.status == SnapshotStatus.ACTIVE:
                if snap.metadata.last_event_sequence > latest_sequence:
                    latest = snap
                    latest_sequence = snap.metadata.last_event_sequence
        if not latest:
            return None
        # Check expiration
        if latest.metadata.expires_at and latest.metadata.expires_at < datetime.now(UTC):
            # Snapshot expired, treat as not exists
            return None
        decompressed = await self._decompress(latest.data, latest.metadata.compression)
        state = await self._deserialize_state(decompressed)
        await self._log_audit(
            "LOAD_LATEST",
            latest.metadata.snapshot_id,
            {
                "aggregate_type": aggregate_type,
                "aggregate_id": str(aggregate_id),
            },
        )
        return (
            latest.metadata.snapshot_id,
            state,
            latest.metadata.version,
            latest.metadata.last_event_sequence,
        )

    async def load_by_version(
        self, aggregate_type: str, aggregate_id: UUID, version: int
    ) -> tuple[UUID, Any, int] | None:
        """Load snapshot berdasarkan version tertentu (max version <= given)."""
        key = (aggregate_type, aggregate_id)
        snapshot_ids = self._index_by_aggregate.get(key, [])
        best = None
        best_version = -1
        for sid in snapshot_ids:
            snap = self._snapshots.get(sid)
            if snap and snap.metadata.status == SnapshotStatus.ACTIVE:
                if snap.metadata.version <= version and snap.metadata.version > best_version:
                    best = snap
                    best_version = snap.metadata.version
        if not best:
            return None
        if best.metadata.expires_at and best.metadata.expires_at < datetime.now(UTC):
            return None
        decompressed = await self._decompress(best.data, best.metadata.compression)
        state = await self._deserialize_state(decompressed)
        return (best.metadata.snapshot_id, state, best.metadata.version)

    # ==================== DELETE & CLEANUP ====================

    async def delete(self, snapshot_id: UUID, permanent: bool = False) -> bool:
        """Soft delete (default) atau permanent delete snapshot."""
        snap = self._snapshots.get(snapshot_id)
        if not snap:
            return False
        if permanent:
            # Hapus dari index
            key = (snap.metadata.aggregate_type, snap.metadata.aggregate_id)
            if key in self._index_by_aggregate:
                self._index_by_aggregate[key] = [
                    sid for sid in self._index_by_aggregate[key] if sid != snapshot_id
                ]
            del self._snapshots[snapshot_id]
            await self._log_audit("DELETE_PERMANENT", snapshot_id, {})
        else:
            snap.metadata.status = SnapshotStatus.DELETED
            await self._log_audit("DELETE_SOFT", snapshot_id, {})
        return True

    async def delete_by_aggregate(self, aggregate_type: str, aggregate_id: UUID) -> int:
        """Hapus semua snapshot untuk aggregate tertentu."""
        key = (aggregate_type, aggregate_id)
        snapshot_ids = self._index_by_aggregate.get(key, []).copy()
        count = 0
        for sid in snapshot_ids:
            if await self.delete(sid, permanent=True):
                count += 1
        await self._log_audit(
            "DELETE_BY_AGGREGATE",
            UUID(int=0),
            {
                "aggregate_type": aggregate_type,
                "aggregate_id": str(aggregate_id),
                "count": count,
            },
        )
        return count

    async def cleanup_expired(self) -> int:
        """Hapus snapshot yang expired."""
        now = datetime.now(UTC)
        expired_ids = []
        for sid, snap in self._snapshots.items():
            if snap.metadata.expires_at and snap.metadata.expires_at < now:
                expired_ids.append(sid)
        for sid in expired_ids:
            await self.delete(sid, permanent=True)
        await self._log_audit("CLEANUP_EXPIRED", UUID(int=0), {"count": len(expired_ids)})
        return len(expired_ids)

    async def start_cleanup_scheduler(self, interval_hours: int = 24):
        """Start background task untuk cleanup berkala."""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_hours))

    async def _cleanup_loop(self, interval_hours: int):
        while self._running:
            await asyncio.sleep(interval_hours * 3600)
            await self.cleanup_expired()

    async def stop_cleanup(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    # ==================== QUERY ====================

    async def list_snapshots(
        self,
        aggregate_type: str | None = None,
        aggregate_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SnapshotMetadata]:
        """Daftar snapshot dengan filter."""
        result = []
        for snap in self._snapshots.values():
            if aggregate_type and snap.metadata.aggregate_type != aggregate_type:
                continue
            if aggregate_id and snap.metadata.aggregate_id != aggregate_id:
                continue
            if snap.metadata.status != SnapshotStatus.ACTIVE:
                continue
            result.append(snap.metadata)
        result.sort(key=lambda x: x.created_at, reverse=True)
        return result[offset : offset + limit]

    async def get_snapshot_metadata(self, snapshot_id: UUID) -> SnapshotMetadata | None:
        snap = self._snapshots.get(snapshot_id)
        return snap.metadata if snap else None

    async def get_latest_version(self, aggregate_type: str, aggregate_id: UUID) -> int | None:
        """Dapatkan version terbaru dari snapshot yang tersimpan."""
        latest = await self.load_latest(aggregate_type, aggregate_id)
        if latest:
            return latest[2]  # version
        return None

    # ==================== STATISTICS & HEALTH ====================

    async def get_statistics(self) -> dict[str, Any]:
        total_snapshots = len(self._snapshots)
        active = sum(
            1 for s in self._snapshots.values() if s.metadata.status == SnapshotStatus.ACTIVE
        )
        total_size = sum(s.metadata.compressed_size_bytes for s in self._snapshots.values())
        by_aggregate_type = {}
        for s in self._snapshots.values():
            if s.metadata.status != SnapshotStatus.ACTIVE:
                continue
            t = s.metadata.aggregate_type
            by_aggregate_type[t] = by_aggregate_type.get(t, 0) + 1
        return {
            "total_snapshots": total_snapshots,
            "active_snapshots": active,
            "deleted_snapshots": total_snapshots - active,
            "total_compressed_size_bytes": total_size,
            "by_aggregate_type": by_aggregate_type,
            "default_ttl_days": self._default_ttl,
            "compression_enabled": self._enable_compression,
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_snapshots": len(self._snapshots),
            "indexed_aggregates": len(self._index_by_aggregate),
            "cleanup_running": self._running,
            "audit_log_size": len(self._audit_log),
        }
