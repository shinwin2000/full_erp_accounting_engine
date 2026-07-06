#!/usr/bin/env python3
"""
Module: outbox_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel outbox.
               Tabel ini menyimpan event yang akan dikirim ke message broker (Kafka)
               sebagai bagian dari transactional outbox pattern.

Versi hardened: Menambahkan field-field yang diperlukan untuk kepatuhan penuh
terhadap aturan Outbox Pattern:
- event_id (OUT-003): unique identifier per event
- idempotency_key (OUT-008): untuk deduplikasi
- processed_at (OUT-005): waktu pemrosesan
- version (OUT-010): optimistic locking
- priority (OUT-011): prioritas event
- scheduled_at (OUT-012): penjadwalan
- correlation_id (OUT-009): tracing
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
        # Indeks untuk performa query
        Index("idx_outbox_status", "status"),
        Index("idx_outbox_event_type", "event_type"),
        Index("idx_outbox_aggregate", "aggregate_type", "aggregate_id"),
        Index("idx_outbox_created_at", "created_at"),
        Index("idx_outbox_updated_at", "updated_at"),
        Index("idx_outbox_deleted_at", "deleted_at"),
        Index("idx_outbox_next_retry", "next_retry_at"),
        Index("idx_outbox_legal_entity", "legal_entity_id"),
        # Indeks untuk field baru
        Index("idx_outbox_event_id", "event_id", unique=True),          # OUT-003
        Index("idx_outbox_idempotency_key", "idempotency_key", unique=True),  # OUT-008
        Index("idx_outbox_processed_at", "processed_at"),
        Index("idx_outbox_priority", "priority"),
        Index("idx_outbox_scheduled_at", "scheduled_at"),
        Index("idx_outbox_correlation_id", "correlation_id"),
        {"extend_existing": True},
    )

    # Primary key dan field wajib
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string

    # Status dan retry
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Legal entity (opsional)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # ========================================================================
    # FIELD TAMBAHAN UNTUK KEPATUHAN OUTBOX PATTERN
    # ========================================================================

    # OUT-003: Unique event identifier
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4
    )

    # OUT-008: Idempotency key (untuk deduplikasi)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # OUT-005: Waktu pemrosesan
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # OUT-010: Optimistic locking version
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # OUT-011: Prioritas (semakin kecil angka semakin tinggi prioritas)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # OUT-012: Waktu penjadwalan (untuk delayed delivery)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # OUT-009: Correlation ID untuk tracing
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
            delay = min(2**self.retry_count, 60)  # exponential backoff sederhana
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
            "event_id": str(self.event_id),
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
            "idempotency_key": self.idempotency_key,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "version": self.version,
            "priority": self.priority,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "correlation_id": self.correlation_id,
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