#!/usr/bin/env python3
"""
Module: background_task_monitor.py
Layer: Infrastructure
Responsibility: Memonitor background tasks (asyncio tasks) yang berjalan.
               Menyediakan fungsi untuk mendapatkan daftar task aktif,
               membatalkan (revoke) task, dan mencatat status task.
               Untuk keperluan administratif via API.
Dependencies:
- asyncio, logging, uuid, typing
- infrastructure.telemetry.structured_json_logging
Audit: Setiap task yang di-revoke dicatat.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# TASK REGISTRY
# ============================================================================


class BackgroundTaskMonitor:
    """
    Monitor untuk background tasks asyncio.
    Menyimpan metadata task dan menyediakan cancellation.
    """

    def __init__(self):
        self._tasks: dict[str, dict[str, Any]] = {}
        self._cancellation_flags: dict[str, bool] = {}

    def register_task(
        self, task: asyncio.Task, name: str = None, metadata: dict[str, Any] = None
    ) -> str:
        """
        Mendaftarkan task ke monitor.
        Args:
            task: asyncio.Task object
            name: Nama task (opsional)
            metadata: Metadata tambahan (opsional)
        Returns:
            task_id: UUID string sebagai identifier
        """
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = {
            "id": task_id,
            "task": task,
            "name": name or task.get_name(),
            "status": "running",
            "created_at": datetime.utcnow(),
            "metadata": metadata or {},
        }
        self._cancellation_flags[task_id] = False
        # Tambahkan callback untuk menghapus task saat selesai
        task.add_done_callback(lambda _: self._unregister_task(task_id))
        logger.info(f"Registered background task {task_id} ({name})")
        return task_id

    def _unregister_task(self, task_id: str) -> None:
        """Hapus task dari registry setelah selesai."""
        if task_id in self._tasks:
            task_info = self._tasks.pop(task_id)
            task_info["status"] = "completed"
            logger.debug(f"Task {task_id} completed and removed from registry")
        self._cancellation_flags.pop(task_id, None)

    async def get_active_tasks(self) -> list[dict[str, Any]]:
        """Mengembalikan daftar task yang sedang berjalan (tidak selesai)."""
        active = []
        for task_id, info in self._tasks.items():
            task = info["task"]
            if not task.done():
                active.append(
                    {
                        "id": task_id,
                        "name": info["name"],
                        "status": "running",
                        "created_at": info["created_at"].isoformat(),
                        "metadata": info["metadata"],
                    }
                )
        return active

    def should_cancel(self, task_id: str) -> bool:
        """Cek apakah task dengan ID tertentu harus dibatalkan."""
        return self._cancellation_flags.get(task_id, False)

    async def revoke_task(self, task_id: str) -> bool:
        """
        Meminta pembatalan task.
        Args:
            task_id: ID task yang akan dibatalkan
        Returns:
            bool: True jika task ditemukan dan flag cancel diset, False jika tidak ditemukan
        """
        if task_id not in self._tasks:
            logger.warning(f"Attempt to revoke unknown task {task_id}")
            return False
        self._cancellation_flags[task_id] = True
        # Jika task masih running, coba cancel langsung (opsional)
        task_info = self._tasks[task_id]
        task = task_info["task"]
        if not task.done():
            task.cancel()
            logger.info(f"Revoked task {task_id} ({task_info['name']}) via cancellation")
        else:
            logger.info(f"Task {task_id} already completed, cannot revoke")
        return True


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_task_monitor: BackgroundTaskMonitor | None = None


def get_task_monitor() -> BackgroundTaskMonitor:
    global _task_monitor
    if _task_monitor is None:
        _task_monitor = BackgroundTaskMonitor()
    return _task_monitor


# ============================================================================
# PUBLIC API FUNCTIONS (sesuai yang diharapkan router)
# ============================================================================


async def get_active_tasks() -> list[dict[str, Any]]:
    """
    Mendapatkan daftar task aktif.
    Sesuai dengan yang dipanggil di fastapi_maintenance_router.py
    """
    monitor = get_task_monitor()
    return await monitor.get_active_tasks()


async def revoke_task(task_id: str) -> bool:
    """
    Membatalkan task berdasarkan ID.
    Sesuai dengan yang dipanggil di fastapi_maintenance_router.py
    """
    monitor = get_task_monitor()
    return await monitor.revoke_task(task_id)


def register_task(task: asyncio.Task, name: str = None, metadata: dict[str, Any] = None) -> str:
    """
    Helper untuk mendaftarkan task dari kode lain (misalnya saat membuat background process).
    """
    monitor = get_task_monitor()
    return monitor.register_task(task, name, metadata)


def should_cancel_current_task(task_id: str) -> bool:
    """
    Fungsi yang bisa dipanggil di dalam task untuk mengecek apakah harus berhenti.
    """
    monitor = get_task_monitor()
    return monitor.should_cancel(task_id)


__all__ = [
    "BackgroundTaskMonitor",
    "get_active_tasks",
    "get_task_monitor",
    "register_task",
    "revoke_task",
    "should_cancel_current_task",
]
