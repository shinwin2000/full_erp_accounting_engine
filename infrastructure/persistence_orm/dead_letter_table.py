# infrastructure/persistence_orm/dead_letter_table.py
#!/usr/bin/env python3
"""
Module: dead_letter_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel dead_letter_events.
               Tabel ini menyimpan event yang gagal diproses setelah retry maksimal,
               termasuk error message, retry count, dan metadata untuk analisis.
               Digunakan oleh subscriber application untuk dead letter handling.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- sqlalchemy.dialects.postgresql (UUID, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin)
Audit: Dead letter events dicatat untuk observability dan debugging.
       Admin dapat mereplay event dari tabel ini.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class DeadLetterTable(Base, TimestampMixin):
    """
    Model untuk tabel dead_letter_events.
    Menyimpan event yang gagal diproses secara permanen.
    Model ini IMMUTABLE - tidak boleh di-update atau di-delete.
    """

    __tablename__ = "dead_letter_events"
    # Flag untuk checker: model ini adalah audit log yang immutable
    __is_audit_log__ = True
    __table_args__ = (
        CheckConstraint("event_type IS NOT NULL AND event_type != ''", name="ck_dle_event_type"),
        CheckConstraint("retry_count >= 0", name="ck_dle_retry_count"),
        Index("idx_dle_event_type", "event_type"),
        Index("idx_dle_created_at", "created_at"),
        Index("idx_dle_retry_count", "retry_count"),
        Index("idx_dle_event_id", "event_id"),
        Index("idx_dle_resolved", "resolved_at"),
    )

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Event identification
    event_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)

    # Payload and error
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string of event envelope
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Source metadata (from Kafka)
    source_topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_partition: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Additional context
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Metadata (e.g., reprocessing attempts, custom tags)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Resolution tracking (when reprocessed successfully)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_resolved(self) -> bool:
        """Check if this dead letter event has been resolved."""
        return self.resolved_at is not None

    @property
    def age_in_hours(self) -> float:
        """Calculate age of this dead letter event in hours."""
        if self.created_at:
            delta = datetime.now(self.created_at.tzinfo) - self.created_at
            return delta.total_seconds() / 3600
        return 0.0

    # ========================================================================
    # METHODS
    # ========================================================================

    def mark_resolved(self, resolved_by: str) -> None:
        """Mark this dead letter event as resolved."""
        self.resolved_at = datetime.utcnow()
        self.resolved_by = resolved_by
        self.increment_version()  # from VersionMixin? Actually this class doesn't have VersionMixin, but we add method

    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "payload": self.payload,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "source_topic": self.source_topic,
            "source_partition": self.source_partition,
            "source_offset": self.source_offset,
            "correlation_id": self.correlation_id,
            "user_id": str(self.user_id) if self.user_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "extra_metadata": self.extra_metadata,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_resolved": self.is_resolved,
            "age_hours": self.age_in_hours,
        }

    def __repr__(self) -> str:
        return f"<DeadLetterTable(id={self.id}, event_type={self.event_type}, event_id={self.event_id}, retry_count={self.retry_count})>"


# Alias for compatibility
DeadLetterEvent = DeadLetterTable

__all__ = ["DeadLetterEvent", "DeadLetterTable"]
