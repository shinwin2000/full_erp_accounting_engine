#!/usr/bin/env python3
"""
Module: outbox_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel outbox.
               Tabel ini menyimpan event yang akan dikirim ke message broker (Kafka)
               sebagai bagian dari transactional outbox pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
)


class OutboxStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "sent"
    PUBLISHED_DUPLICATE = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class OutboxTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("event_type IS NOT NULL AND event_type != ''", name="ck_outbox_event_type"),
        CheckConstraint("aggregate_type IS NOT NULL", name="ck_outbox_aggregate_type"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed', 'dead_letter')",
            name="ck_outbox_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_outbox_retry_nonneg"),
        Index("idx_outbox_status", "status"),
        Index("idx_outbox_event_type", "event_type"),
        Index("idx_outbox_aggregate", "aggregate_type", "aggregate_id"),
        Index("idx_outbox_created_at", "created_at"),
        Index("idx_outbox_updated_at", "updated_at"),
        Index("idx_outbox_deleted_at", "deleted_at"),
        Index("idx_outbox_next_retry", "next_retry_at"),
        Index("idx_outbox_legal_entity", "legal_entity_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string

    # extra_metadata dihapus � tidak ada di database

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # legal_entity_id opsional (tanpa foreign key)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_processing(self) -> bool:
        return self.status == "processing"

    @property
    def is_sent(self) -> bool:
        return self.status == "sent"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @property
    def is_dead_letter(self) -> bool:
        return self.status == "dead_letter"

    @property
    def is_ready_for_retry(self) -> bool:
        if self.status != "pending":
            return False
        if self.next_retry_at is None:
            return True
        return datetime.now(UTC) >= self.next_retry_at

    # ========================================================================
    # METHODS
    # ========================================================================

    def mark_processing(self) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot mark as processing with status {self.status}")
        self.status = "processing"

    def mark_sent(self) -> None:
        if self.status != "processing":
            raise ValueError(f"Cannot mark as sent with status {self.status}")
        self.status = "sent"
        self.sent_at = datetime.now(UTC)

    def mark_failed(self, error: str, schedule_retry: bool = True) -> None:
        if self.status not in ("pending", "processing"):
            raise ValueError(f"Cannot mark as failed with status {self.status}")
        self.status = "pending"
        self.retry_count += 1
        self.last_error = error
        if schedule_retry:
            delay = min(2**self.retry_count, 60)
            self.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        else:
            self.next_retry_at = None

    def mark_dead_letter(self, error: str) -> None:
        self.status = "dead_letter"
        self.last_error = error
        self.next_retry_at = None

    def reset_retry(self) -> None:
        self.retry_count = 0
        self.last_error = None
        self.next_retry_at = None
        self.status = "pending"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "payload": self.payload,
            "status": self.status,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


# ============================================================================
# Alias for backward compatibility
# ============================================================================

OutboxRecord = OutboxTable


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["OutboxRecord", "OutboxStatus", "OutboxTable"]
