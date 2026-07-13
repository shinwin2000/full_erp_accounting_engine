#!/usr/bin/env python3
"""
Module: event_publisher_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk Event Publisher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class EventStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"
    SKIPPED = "skipped"


class EventPublisherPort(ABC):
    """
    Port interface untuk event publisher dengan outbox pattern.
    Semua metode wajib diimplementasikan oleh adapter (in-memory, SQLAlchemy, dll).
    """

    @abstractmethod
    async def publish(
        self,
        event: Any,
        event_type: str,
        aggregate_id: UUID,
        aggregate_type: str,
        metadata: dict[str, Any] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        scheduled_at: datetime | None = None,
        idempotency_key: str | None = None,
        partition_key: str | None = None,
        event_version: int = 1,
    ) -> UUID:
        """Publikasikan event ke outbox."""
        pass

    @abstractmethod
    async def publish_batch(self, events: list[dict[str, Any]]) -> list[UUID]:
        """Publikasikan banyak event sekaligus."""
        pass

    @abstractmethod
    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]],
        name: str | None = None,
        timeout_seconds: int = 30,
        retry_on_failure: bool = True,
    ) -> None:
        """Daftarkan handler untuk event type."""
        pass

    @abstractmethod
    def unsubscribe(self, event_type: str, name: str) -> bool:
        """Hapus subscriber berdasarkan nama."""
        pass

    @abstractmethod
    async def start_poller(self):
        """Start background poller untuk memproses outbox."""
        pass

    @abstractmethod
    async def stop_poller(self):
        """Stop background poller."""
        pass

    @abstractmethod
    async def get_event_status(self, event_id: UUID) -> dict[str, Any] | None:
        """Dapatkan status event."""
        pass

    @abstractmethod
    async def get_pending_count(self) -> int:
        """Jumlah event pending."""
        pass

    @abstractmethod
    async def get_processing_count(self) -> int:
        """Jumlah event processing."""
        pass

    @abstractmethod
    async def get_failed_count(self) -> int:
        """Jumlah event failed."""
        pass

    @abstractmethod
    async def get_dead_letter_count(self) -> int:
        """Jumlah event di dead letter."""
        pass

    @abstractmethod
    async def get_outbox_size(self) -> int:
        """Total event di outbox."""
        pass

    @abstractmethod
    async def flush(self) -> int:
        """Proses semua pending events secara sinkron."""
        pass

    @abstractmethod
    async def purge_outbox(self, older_than_days: int = 30) -> int:
        """Hapus event SENT yang sudah lama."""
        pass

    @abstractmethod
    async def retry_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> UUID | None:
        """Kirim ulang event dari dead letter."""
        pass

    @abstractmethod
    async def skip_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> bool:
        """Tandai dead letter sebagai skipped."""
        pass

    @abstractmethod
    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[Any]:
        """Daftar dead letters."""
        pass

    @abstractmethod
    async def purge_dead_letters(self, older_than_days: int = 30) -> int:
        """Hapus dead letter lama."""
        pass

    @abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        """Statistik publisher."""
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Ambil audit log."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


__all__ = ["EventPriority", "EventPublisherPort", "EventStatus"]
