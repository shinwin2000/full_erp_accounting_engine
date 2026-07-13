#!/usr/bin/env python3
"""
Module: read_model_projection_port.py
Layer: Ports (Secondary)
Responsibility: Antarmuka dan implementasi in-memory untuk read model projection.
               Mendukung pendaftaran projector, pemrosesan event, checkpoint
               untuk exactly-once semantics, rebuild, catch-up, versioning,
               dan monitoring.
Audit: Setiap proyeksi event dan rebuild tercatat.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


class ProjectionStatus(Enum):
    """Status proyeksi (read model)."""

    ACTIVE = "active"
    REBUILDING = "rebuilding"
    PAUSED = "paused"
    FAILED = "failed"


class ProjectionVersion(Enum):
    """Versi proyeksi untuk migrasi."""

    V1 = 1
    V2 = 2
    V3 = 3
    LATEST = 999


@dataclass
class Checkpoint:
    """Checkpoint untuk projector (posisi terakhir yang diproses)."""

    projector_name: str
    last_event_id: UUID
    last_event_sequence: int
    last_processed_at: datetime
    processed_count: int
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "projector_name": self.projector_name,
            "last_event_id": str(self.last_event_id),
            "last_event_sequence": self.last_event_sequence,
            "last_processed_at": self.last_processed_at.isoformat(),
            "processed_count": self.processed_count,
            "version": self.version,
        }


@dataclass
class ProjectionEvent:
    """Event yang masuk ke projector."""

    id: UUID
    sequence: int
    event_type: str
    aggregate_id: UUID
    aggregate_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    occurred_at: datetime


class ProjectionError(Exception):
    """Error dalam proyeksi."""

    pass


class Projector(Protocol):
    """Protocol untuk projector (harus diimplementasikan oleh adapter)."""

    @property
    def name(self) -> str: ...
    @property
    def version(self) -> int: ...
    async def can_handle(self, event_type: str) -> bool: ...
    async def handle(self, event: ProjectionEvent) -> None: ...
    async def rebuild(self) -> None: ...


class ReadModelProjectionPort:
    """
    In-memory implementation of read model projection.
    """

    def __init__(self):
        self._projectors: dict[str, Projector] = {}
        self._checkpoints: dict[str, Checkpoint] = {}
        self._status: dict[str, ProjectionStatus] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()
        self._audit_log: list[dict[str, Any]] = []
        self._processed_events: set[UUID] = set()  # idempotency
        self._stats: dict[str, dict[str, Any]] = {}
        # ===== PERBAIKAN: Simpan referensi task =====
        self._pending_tasks: list[asyncio.Task] = []

    def _add_pending_task(self, task: asyncio.Task) -> None:
        """Tambahkan task ke daftar pending dan daftarkan callback untuk menghapusnya."""
        self._pending_tasks.append(task)
        task.add_done_callback(
            lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None
        )

    # ==================== HELPER ====================

    async def _log_audit(self, action: str, projector_name: str, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "projector": projector_name,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"PROJECTION AUDIT: {action} on {projector_name}")

    # ==================== PROJECTOR MANAGEMENT ====================

    def register_projector(self, projector: Projector) -> None:
        """Daftarkan projector untuk read model."""
        if projector.name in self._projectors:
            raise ValueError(f"Projector {projector.name} already registered")
        self._projectors[projector.name] = projector
        self._status[projector.name] = ProjectionStatus.ACTIVE
        self._stats[projector.name] = {
            "processed": 0,
            "last_event_sequence": 0,
            "errors": 0,
            "last_error": None,
        }
        logger.info(f"Projector '{projector.name}' registered (version {projector.version})")

    def unregister_projector(self, name: str) -> bool:
        if name in self._projectors:
            del self._projectors[name]
            self._status.pop(name, None)
            return True
        return False

    async def get_checkpoint(self, projector_name: str) -> Checkpoint | None:
        """Ambil checkpoint terakhir untuk projector."""
        return self._checkpoints.get(projector_name)

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Simpan checkpoint (biasanya dipanggil setelah batch events)."""
        async with self._lock:
            self._checkpoints[checkpoint.projector_name] = checkpoint
        await self._log_audit(
            "CHECKPOINT",
            checkpoint.projector_name,
            {
                "event_id": str(checkpoint.last_event_id),
                "sequence": checkpoint.last_event_sequence,
                "count": checkpoint.processed_count,
            },
        )

    # ==================== EVENT PROCESSING ====================

    async def submit_event(self, event: ProjectionEvent) -> None:
        """Kirim event ke queue untuk diproses oleh projectors."""
        # Idempotency: cek apakah event sudah pernah diproses
        if event.id in self._processed_events:
            logger.debug(f"Event {event.id} already processed, skipping")
            return
        await self._event_queue.put(event)
        await self._log_audit(
            "QUEUE_EVENT",
            "system",
            {
                "event_id": str(event.id),
                "event_type": event.event_type,
                "sequence": event.sequence,
            },
        )

    async def submit_batch(self, events: list[ProjectionEvent]) -> None:
        """Kirim batch events."""
        for event in events:
            await self.submit_event(event)

    # ========================================================================
    # PERBAIKAN: start_worker dengan task management
    # ========================================================================

    async def start_worker(self, concurrency: int = 4):
        """Start background worker untuk memproses queue."""
        if self._running:
            logger.warning("Worker already running")
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop(concurrency))
        self._add_pending_task(self._worker_task)
        logger.info("Projection worker started")

    # ========================================================================
    # PERBAIKAN: _worker_loop menggunakan _add_pending_task
    # ========================================================================

    async def _worker_loop(self, concurrency: int):
        semaphore = asyncio.Semaphore(concurrency)
        while self._running:
            try:
                event = await self._event_queue.get()
                async with semaphore:
                    # ===== PERBAIKAN: Simpan task ke pending list =====
                    task = asyncio.create_task(self._process_event(event))
                    self._add_pending_task(task)
            except asyncio.CancelledError:
                logger.debug("Projection worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")

    # ========================================================================
    # PERBAIKAN: stop_worker membatalkan semua pending tasks
    # ========================================================================

    async def stop_worker(self):
        self._running = False
        # Batalkan semua pending tasks
        if self._pending_tasks:
            for task in self._pending_tasks:
                if not task.done():
                    task.cancel()
            # Tunggu hingga semua task selesai
            if self._pending_tasks:
                await asyncio.gather(*self._pending_tasks, return_exceptions=True)
                self._pending_tasks.clear()
        self._worker_task = None
        logger.info("Projection worker stopped")

    # ========================================================================

    async def _process_event(self, event: ProjectionEvent):
        """Kirim event ke semua projector yang bisa handle."""
        # Idempotency check lagi di sini
        if event.id in self._processed_events:
            return
        for name, projector in self._projectors.items():
            if self._status.get(name) != ProjectionStatus.ACTIVE:
                continue
            try:
                if await projector.can_handle(event.event_type):
                    await projector.handle(event)
                    # Update stats
                    self._stats[name]["processed"] += 1
                    self._stats[name]["last_event_sequence"] = max(
                        self._stats[name]["last_event_sequence"], event.sequence
                    )
            except Exception as e:
                self._stats[name]["errors"] += 1
                self._stats[name]["last_error"] = str(e)
                logger.error(f"Projector {name} failed to handle event {event.id}: {e}")
                # Optional: pause projector after too many errors
        # Mark as processed
        async with self._lock:
            self._processed_events.add(event.id)
        await self._log_audit(
            "PROCESS_EVENT",
            "system",
            {
                "event_id": str(event.id),
                "event_type": event.event_type,
                "projectors": [p for p in self._projectors.keys()],
            },
        )

    # ==================== REBUILD ====================

    async def rebuild_projector(self, projector_name: str) -> None:
        """Rebuild seluruh read model untuk projector tertentu."""
        if projector_name not in self._projectors:
            raise ValueError(f"Projector {projector_name} not found")
        self._status[projector_name] = ProjectionStatus.REBUILDING
        await self._log_audit("REBUILD_START", projector_name, {})
        try:
            projector = self._projectors[projector_name]
            await projector.rebuild()
            # Reset checkpoint
            checkpoint = await self.get_checkpoint(projector_name)
            if checkpoint:
                checkpoint.processed_count = 0
                checkpoint.last_event_sequence = 0
                checkpoint.last_event_id = UUID(int=0)
                await self.save_checkpoint(checkpoint)
            self._status[projector_name] = ProjectionStatus.ACTIVE
            self._stats[projector_name]["processed"] = 0
            self._stats[projector_name]["errors"] = 0
            await self._log_audit("REBUILD_COMPLETE", projector_name, {})
        except Exception as e:
            self._status[projector_name] = ProjectionStatus.FAILED
            await self._log_audit("REBUILD_FAILED", projector_name, {"error": str(e)})
            raise

    async def rebuild_all(self) -> dict[str, bool]:
        """Rebuild semua projector."""
        results = {}
        for name in self._projectors.keys():
            try:
                await self.rebuild_projector(name)
                results[name] = True
            except Exception:
                results[name] = False
        return results

    async def pause_projector(self, projector_name: str) -> bool:
        """Pause projector (stop processing events)."""
        if projector_name not in self._projectors:
            return False
        self._status[projector_name] = ProjectionStatus.PAUSED
        await self._log_audit("PAUSE", projector_name, {})
        return True

    async def resume_projector(self, projector_name: str) -> bool:
        if projector_name not in self._projectors:
            return False
        self._status[projector_name] = ProjectionStatus.ACTIVE
        await self._log_audit("RESUME", projector_name, {})
        return True

    # ==================== QUERY STATS ====================

    async def get_projector_status(self, projector_name: str) -> dict[str, Any] | None:
        if projector_name not in self._projectors:
            return None
        checkpoint = await self.get_checkpoint(projector_name)
        return {
            "name": projector_name,
            "status": self._status.get(projector_name, ProjectionStatus.FAILED).value,
            "version": self._projectors[projector_name].version,
            "checkpoint": checkpoint.to_dict() if checkpoint else None,
            "stats": self._stats.get(projector_name, {}),
        }

    async def get_all_status(self) -> dict[str, dict[str, Any]]:
        result = {}
        for name in self._projectors.keys():
            result[name] = await self.get_projector_status(name)
        return result

    async def get_queue_size(self) -> int:
        return self._event_queue.qsize()

    async def get_metrics(self) -> dict[str, Any]:
        total_processed = sum(s["processed"] for s in self._stats.values())
        total_errors = sum(s["errors"] for s in self._stats.values())
        return {
            "queue_size": await self.get_queue_size(),
            "total_processed_events": total_processed,
            "total_errors": total_errors,
            "active_projectors": len(
                [p for p, s in self._status.items() if s == ProjectionStatus.ACTIVE]
            ),
            "paused_projectors": len(
                [p for p, s in self._status.items() if s == ProjectionStatus.PAUSED]
            ),
            "rebuilding_projectors": len(
                [p for p, s in self._status.items() if s == ProjectionStatus.REBUILDING]
            ),
        }

    # ==================== CATCH-UP ====================

    async def catch_up(self, projector_name: str, events: list[ProjectionEvent]) -> int:
        """Proses missed events untuk catch-up (tanpa queue)."""
        if projector_name not in self._projectors:
            raise ValueError(f"Projector {projector_name} not found")
        projector = self._projectors[projector_name]
        if self._status.get(projector_name) != ProjectionStatus.ACTIVE:
            raise ValueError(f"Projector {projector_name} is not active")
        count = 0
        for event in events:
            if await projector.can_handle(event.event_type):
                await projector.handle(event)
                count += 1
        return count

    # ==================== AUDIT ====================

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "worker_running": self._running,
            "queue_size": self._event_queue.qsize(),
            "registered_projectors": len(self._projectors),
            "checkpoints": len(self._checkpoints),
            "processed_events_set": len(self._processed_events),
            "audit_log_size": len(self._audit_log),
        }


# ==================== EXAMPLE PROJECTOR IMPLEMENTATION ====================


class BaseProjector:
    """Base class untuk projector (bisa di-extends)."""

    def __init__(self, name: str, version: int = 1):
        self._name = name
        self._version = version
        self._handlers: dict[str, Callable[[ProjectionEvent], Awaitable[None]]] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> int:
        return self._version

    def register_handler(
        self, event_type: str, handler: Callable[[ProjectionEvent], Awaitable[None]]
    ):
        self._handlers[event_type] = handler

    async def can_handle(self, event_type: str) -> bool:
        return event_type in self._handlers

    async def handle(self, event: ProjectionEvent) -> None:
        handler = self._handlers.get(event.event_type)
        if handler:
            await handler(event)

    async def rebuild(self) -> None:
        """Override this method to rebuild read model."""
        raise NotImplementedError("Subclasses must implement rebuild")
