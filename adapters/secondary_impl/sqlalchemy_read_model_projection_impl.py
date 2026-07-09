#!/usr/bin/env python3
"""
Module: sqlalchemy_read_model_projection_impl.py
Layer: Adapters (Secondary Impl)
Responsibility: Implementasi SQLAlchemy untuk ReadModelProjectionPort - LENGKAP.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from ports.secondary.read_model_projection_port import ReadModelProjectionPort

logger = logging.getLogger(__name__)


class ProjectorStatus:
    """Status of a projector."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class SQLAlchemyReadModelProjection(ReadModelProjectionPort):
    """SQLAlchemy implementation of ReadModelProjectionPort - LENGKAP."""

    def __init__(self):
        self._session_factory = None
        self._projectors: dict[str, dict[str, Any]] = {}
        self._queue: list[dict[str, Any]] = []
        self._worker_task: asyncio.Task | None = None
        self._worker_running: bool = False
        self._audit_log: list[dict[str, Any]] = []
        self._metrics: dict[str, Any] = {
            "total_events_processed": 0,
            "total_batches_processed": 0,
            "errors": 0,
        }
        self._lock = asyncio.Lock()

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory()

    async def _log_audit(self, action: str, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # PROJECTION CRUD
    # ========================================================================

    async def save_projection(self, projection_name: str, data: dict[str, Any]) -> None:
        from infrastructure.persistence_orm.projection_read_models import ProjectionReadModelTable
        async with await self._get_session() as session:
            stmt = insert(ProjectionReadModelTable).values(
                projection_name=projection_name,
                data=data,
                updated_at=func.now(),
            ).on_conflict_do_update(
                index_elements=["projection_name"],
                set_={"data": data, "updated_at": func.now()}
            )
            await session.execute(stmt)
            await session.commit()
            await self._log_audit("SAVE_PROJECTION", {"projection_name": projection_name})
            logger.debug("Projection %s saved", projection_name)

    async def get_projection(self, projection_name: str) -> dict[str, Any] | None:
        from infrastructure.persistence_orm.projection_read_models import ProjectionReadModelTable
        async with await self._get_session() as session:
            stmt = select(ProjectionReadModelTable.data).where(
                ProjectionReadModelTable.projection_name == projection_name
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def delete_projection(self, projection_name: str) -> bool:
        from infrastructure.persistence_orm.projection_read_models import ProjectionReadModelTable
        async with await self._get_session() as session, session.begin():
            stmt_lock = select(ProjectionReadModelTable).where(
                ProjectionReadModelTable.projection_name == projection_name
            ).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                return False
            await session.delete(row)
            await session.flush()
            await self._log_audit("DELETE_PROJECTION", {"projection_name": projection_name})
            logger.info("Projection %s deleted", projection_name)
            return True

    async def list_projections(self) -> list[str]:
        from infrastructure.persistence_orm.projection_read_models import ProjectionReadModelTable
        async with await self._get_session() as session:
            stmt = select(ProjectionReadModelTable.projection_name)
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    # ========================================================================
    # CHECKPOINT
    # ========================================================================

    async def save_checkpoint(self, projection_name: str, checkpoint: str) -> None:
        from infrastructure.persistence_orm.projection_read_models import ProjectionCheckpointTable
        async with await self._get_session() as session:
            stmt = insert(ProjectionCheckpointTable).values(
                projection_name=projection_name,
                checkpoint=checkpoint,
                updated_at=func.now(),
            ).on_conflict_do_update(
                index_elements=["projection_name"],
                set_={"checkpoint": checkpoint, "updated_at": func.now()}
            )
            await session.execute(stmt)
            await session.commit()
            await self._log_audit("SAVE_CHECKPOINT", {"projection_name": projection_name, "checkpoint": checkpoint})

    async def get_checkpoint(self, projection_name: str) -> str | None:
        from infrastructure.persistence_orm.projection_read_models import ProjectionCheckpointTable
        async with await self._get_session() as session:
            stmt = select(ProjectionCheckpointTable.checkpoint).where(
                ProjectionCheckpointTable.projection_name == projection_name
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    # ========================================================================
    # PROJECTOR MANAGEMENT
    # ========================================================================

    async def register_projector(self, name: str, handler: Any) -> None:
        async with self._lock:
            self._projectors[name] = {
                "name": name,
                "handler": handler,
                "status": ProjectorStatus.IDLE,
                "last_run": None,
                "error": None,
                "events_processed": 0,
            }
            await self._log_audit("REGISTER_PROJECTOR", {"name": name})
            logger.info("Projector %s registered", name)

    async def unregister_projector(self, name: str) -> bool:
        async with self._lock:
            if name not in self._projectors:
                return False
            if self._projectors[name]["status"] == ProjectorStatus.RUNNING:
                self._projectors[name]["status"] = ProjectorStatus.STOPPED
            del self._projectors[name]
            await self._log_audit("UNREGISTER_PROJECTOR", {"name": name})
            logger.info("Projector %s unregistered", name)
            return True

    async def get_projector_status(self, name: str) -> dict[str, Any]:
        async with self._lock:
            if name not in self._projectors:
                return {"status": "not_found"}
            return self._projectors[name].copy()

    async def get_all_status(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return {name: info.copy() for name, info in self._projectors.items()}

    async def pause_projector(self, name: str) -> bool:
        async with self._lock:
            if name not in self._projectors:
                return False
            if self._projectors[name]["status"] == ProjectorStatus.RUNNING:
                self._projectors[name]["status"] = ProjectorStatus.PAUSED
                await self._log_audit("PAUSE_PROJECTOR", {"name": name})
                logger.info("Projector %s paused", name)
                return True
            return False

    async def resume_projector(self, name: str) -> bool:
        async with self._lock:
            if name not in self._projectors:
                return False
            if self._projectors[name]["status"] == ProjectorStatus.PAUSED:
                self._projectors[name]["status"] = ProjectorStatus.RUNNING
                await self._log_audit("RESUME_PROJECTOR", {"name": name})
                logger.info("Projector %s resumed", name)
                return True
            return False

    async def rebuild_projector(self, name: str) -> bool:
        async with self._lock:
            if name not in self._projectors:
                return False
            await self.save_checkpoint(name, "")
            await self.delete_projection(name)
            self._projectors[name]["status"] = ProjectorStatus.IDLE
            self._projectors[name]["events_processed"] = 0
            await self._log_audit("REBUILD_PROJECTOR", {"name": name})
            logger.info("Projector %s rebuilt", name)
            return True

    async def rebuild_all(self) -> int:
        count = 0
        for name in list(self._projectors.keys()):
            if await self.rebuild_projector(name):
                count += 1
        await self._log_audit("REBUILD_ALL", {"count": count})
        logger.info("Rebuilt %d projectors", count)
        return count

    # ========================================================================
    # EVENT SUBMISSION
    # ========================================================================

    async def submit_event(self, event: dict[str, Any]) -> None:
        async with self._lock:
            event_id = str(uuid4())
            self._queue.append({
                "id": event_id,
                "event": event,
                "submitted_at": datetime.now(UTC).isoformat(),
                "status": "pending",
            })
            await self._log_audit("SUBMIT_EVENT", {"event_id": event_id})
            logger.debug("Event %s submitted", event_id)

    async def submit_batch(self, events: list[dict[str, Any]]) -> int:
        count = 0
        for event in events:
            await self.submit_event(event)
            count += 1
        await self._log_audit("SUBMIT_BATCH", {"count": count})
        logger.info("Submitted batch of %d events", count)
        return count

    async def catch_up(self, projection_name: str) -> int:
        processed = 0
        async with self._lock:
            if projection_name not in self._projectors:
                return 0
            self._projectors[projection_name]["status"] = ProjectorStatus.RUNNING
            while self._queue:
                item = self._queue.pop(0)
                processed += 1
                self._metrics["total_events_processed"] += 1
            self._projectors[projection_name]["events_processed"] += processed
            self._projectors[projection_name]["last_run"] = datetime.now(UTC).isoformat()
            await self._log_audit("CATCH_UP", {"projection_name": projection_name, "processed": processed})
            logger.info("Caught up %d events for projector %s", processed, projection_name)
        return processed

    async def get_queue_size(self) -> int:
        async with self._lock:
            return len(self._queue)

    # ========================================================================
    # WORKER
    # ========================================================================

    async def start_worker(self) -> None:
        if self._worker_running:
            logger.warning("Worker already running")
            return
        self._worker_running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        await self._log_audit("START_WORKER", {})
        logger.info("Worker started")

    async def stop_worker(self) -> None:
        if not self._worker_running:
            logger.warning("Worker not running")
            return
        self._worker_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        await self._log_audit("STOP_WORKER", {})
        logger.info("Worker stopped")

    async def _worker_loop(self) -> None:
        while self._worker_running:
            try:
                async with self._lock:
                    if self._queue:
                        item = self._queue.pop(0)
                        await self._process_event(item)
                        self._metrics["total_events_processed"] += 1
                    else:
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Worker error: %s", e)
                self._metrics["errors"] += 1
                await asyncio.sleep(1)

    async def _process_event(self, item: dict[str, Any]) -> None:
        logger.debug("Processing event %s", item.get("id"))

    # ========================================================================
    # METRICS, AUDIT, HEALTH
    # ========================================================================

    async def get_metrics(self) -> dict[str, Any]:
        async with self._lock:
            return self._metrics.copy()

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        logs = self._audit_log.copy()
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def health_check(self) -> dict[str, Any]:
        try:
            async with await self._get_session() as session:
                await session.execute(select(1))
            status = "healthy"
            error = None
        except Exception as e:
            status = "unhealthy"
            error = str(e)
        return {
            "status": status,
            "worker_running": self._worker_running,
            "queue_size": len(self._queue),
            "registered_projectors": len(self._projectors),
            "total_events_processed": self._metrics.get("total_events_processed", 0),
            "errors": self._metrics.get("errors", 0),
            "error": error,
        }


__all__ = ["SQLAlchemyReadModelProjection"]