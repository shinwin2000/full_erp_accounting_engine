#!/usr/bin/env python3
"""
Module: read_model_projection_port.py
Layer: Ports (Secondary)
Responsibility: Port interface untuk Read Model Projection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ReadModelProjectionPort(ABC):
    """
    Port untuk mengelola read model projections.
    """

    # ---------- Projection CRUD ----------
    @abstractmethod
    async def save_projection(self, projection_name: str, data: dict[str, Any]) -> None:
        """Simpan atau update read model projection."""
        pass

    @abstractmethod
    async def get_projection(self, projection_name: str) -> dict[str, Any] | None:
        """Ambil read model projection berdasarkan nama."""
        pass

    @abstractmethod
    async def delete_projection(self, projection_name: str) -> bool:
        """Hapus read model projection."""
        pass

    @abstractmethod
    async def list_projections(self) -> list[str]:
        """Daftar semua nama projection."""
        pass

    # ---------- Checkpoint ----------
    @abstractmethod
    async def save_checkpoint(self, projection_name: str, checkpoint: str) -> None:
        """Simpan checkpoint untuk projection."""
        pass

    @abstractmethod
    async def get_checkpoint(self, projection_name: str) -> str | None:
        """Ambil checkpoint untuk projection."""
        pass

    # ---------- Projector Management ----------
    @abstractmethod
    async def register_projector(self, name: str, handler: Any) -> None:
        """Daftarkan projector dengan handler."""
        pass

    @abstractmethod
    async def unregister_projector(self, name: str) -> bool:
        """Hapus projector."""
        pass

    @abstractmethod
    async def get_projector_status(self, name: str) -> dict[str, Any]:
        """Status projector tertentu."""
        pass

    @abstractmethod
    async def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Status semua projector."""
        pass

    @abstractmethod
    async def pause_projector(self, name: str) -> bool:
        """Pause projector."""
        pass

    @abstractmethod
    async def resume_projector(self, name: str) -> bool:
        """Resume projector."""
        pass

    @abstractmethod
    async def rebuild_projector(self, name: str) -> bool:
        """Rebuild projector."""
        pass

    @abstractmethod
    async def rebuild_all(self) -> int:
        """Rebuild semua projector."""
        pass

    # ---------- Event Submission ----------
    @abstractmethod
    async def submit_event(self, event: dict[str, Any]) -> None:
        """Kirim satu event untuk diproses."""
        pass

    @abstractmethod
    async def submit_batch(self, events: list[dict[str, Any]]) -> int:
        """Kirim batch events untuk diproses."""
        pass

    @abstractmethod
    async def catch_up(self, projection_name: str) -> int:
        """Proses semua event pending untuk projection tertentu."""
        pass

    @abstractmethod
    async def get_queue_size(self) -> int:
        """Ukuran antrian event."""
        pass

    # ---------- Worker ----------
    @abstractmethod
    async def start_worker(self) -> None:
        """Start background worker."""
        pass

    @abstractmethod
    async def stop_worker(self) -> None:
        """Stop background worker."""
        pass

    # ---------- Metrics & Audit ----------
    @abstractmethod
    async def get_metrics(self) -> dict[str, Any]:
        """Metrics tentang processing."""
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Audit log."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check."""
        pass


__all__ = ["ReadModelProjectionPort"]
