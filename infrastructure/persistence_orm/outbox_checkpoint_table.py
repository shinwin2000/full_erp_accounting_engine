#!/usr/bin/env python3
"""
Module: outbox_checkpoint_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel outbox_checkpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class OutboxCheckpointTable(Base, TimestampMixin):
    __tablename__ = "outbox_checkpoint"
    __table_args__ = (
        UniqueConstraint("relay_id", name="uq_outbox_checkpoint_relay"),
        CheckConstraint("relay_id IS NOT NULL AND relay_id != ''", name="ck_outbox_checkpoint_relay_id"),
        Index("idx_outbox_checkpoint_relay", "relay_id"),
        Index("idx_outbox_checkpoint_last_processed", "last_processed_at")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relay_id: Mapped[str] = mapped_column(String(100), nullable=False)
    last_processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def update_checkpoint(self, event_id: uuid.UUID, timestamp: datetime) -> None:
        self.last_processed_at = timestamp
        self.last_event_id = event_id
        self.processed_count += 1

    def record_error(self) -> None:
        self.error_count += 1

    def reset_errors(self) -> None:
        self.error_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "relay_id": self.relay_id,
            "last_processed_at": self.last_processed_at.isoformat(),
            "last_event_id": str(self.last_event_id) if self.last_event_id else None,
            "processed_count": self.processed_count,
            "error_count": self.error_count,
        }


__all__ = ["OutboxCheckpointTable"]
