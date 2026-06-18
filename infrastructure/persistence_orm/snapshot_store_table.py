#!/usr/bin/env python3
"""
Module: snapshot_store_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel snapshot store.
               Tabel ini menyimpan snapshot dari aggregate untuk event sourcing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base


class SnapshotStoreTable(Base):
    __tablename__ = "snapshot_store"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived', 'deleted')", name="ck_snapshot_status"),
        Index("idx_snapshot_aggregate", "aggregate_id", "aggregate_type", "snapshot_version"),
        Index("idx_snapshot_taken_at", "taken_at"),
        Index("idx_snapshot_status", "status")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    data_format: Mapped[str] = mapped_column(String(20), nullable=False, default="json+zlib")
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def archive(self) -> None:
        self.status = "archived"
        self.archived_at = datetime.utcnow()

    def soft_delete(self) -> None:
        self.status = "deleted"
        self.deleted_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "snapshot_version": self.snapshot_version,
            "data_format": self.data_format,
            "is_encrypted": self.is_encrypted,
            "metadata": self.metadata,
            "taken_at": self.taken_at.isoformat(),
            "status": self.status,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "version": self.version,
        }


__all__ = ["SnapshotStoreTable"]
