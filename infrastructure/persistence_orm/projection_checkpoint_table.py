#!/usr/bin/env python3
"""
Module: projection_checkpoint_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel projection_checkpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class ProjectionCheckpointTable(Base, TimestampMixin):
    __tablename__ = "projection_checkpoint"
    __table_args__ = (
        UniqueConstraint("projection_name", "legal_entity_id", name="uq_projection_checkpoint_name_legal_entity"),
        CheckConstraint("projection_name IS NOT NULL AND projection_name != ''", name="ck_projection_checkpoint_name"),
        Index("idx_projection_checkpoint_name", "projection_name"),
        Index("idx_projection_checkpoint_last_event", "last_event_id"),
        Index("idx_projection_checkpoint_legal_entity", "legal_entity_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    projection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_rebuilding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rebuild_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rebuild_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def update_checkpoint(self, event_id: uuid.UUID, sequence: int) -> None:
        self.last_event_id = event_id
        self.last_event_sequence = sequence
        self.last_processed_at = datetime.utcnow()
        self.processed_count += 1

    def start_rebuild(self) -> None:
        self.is_rebuilding = True
        self.rebuild_started_at = datetime.utcnow()
        self.last_event_sequence = 0
        self.processed_count = 0

    def complete_rebuild(self) -> None:
        self.is_rebuilding = False
        self.rebuild_completed_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "projection_name": self.projection_name,
            "last_event_id": str(self.last_event_id) if self.last_event_id else None,
            "last_event_sequence": self.last_event_sequence,
            "last_processed_at": self.last_processed_at.isoformat(),
            "processed_count": self.processed_count,
            "is_rebuilding": self.is_rebuilding,
            "rebuild_started_at": self.rebuild_started_at.isoformat() if self.rebuild_started_at else None,
            "rebuild_completed_at": self.rebuild_completed_at.isoformat() if self.rebuild_completed_at else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


__all__ = ["ProjectionCheckpointTable"]
