#!/usr/bin/env python3
"""
Module: hash_chain_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel hash_chain.
               Tabel ini menyimpan informasi hash chain per stream untuk
               mempercepat verifikasi integritas. Menyimpan hash terakhir
               dan metadata chain.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin)
Audit: Setiap perubahan status hash chain dicatat.
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class HashChainTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __tablename__ = "hash_chain"
    __table_args__ = (
        UniqueConstraint("stream_name", name="uq_hash_chain_stream"),
        CheckConstraint("stream_name IS NOT NULL AND stream_name != ''", name="ck_hc_stream_name"),
        CheckConstraint("last_hash IS NOT NULL", name="ck_hc_last_hash"),
        CheckConstraint(
            "status IN ('valid', 'broken', 'repairing', 'archived')", name="ck_hc_status"
        ),
        Index("idx_hc_stream_name", "stream_name"),
        Index("idx_hc_status", "status"),
        Index("idx_hc_last_verified", "last_verified_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stream_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    genesis_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="valid")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    broken_at_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repair_history: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def mark_valid(self, verified_by: uuid.UUID | None = None) -> None:
        self.status = "valid"
        self.last_verified_at = datetime.now(UTC)
        self.verified_by = verified_by
        self.broken_at_sequence = None
        self.increment_version()

    def mark_broken(self, broken_at_sequence: int) -> None:
        self.status = "broken"
        self.broken_at_sequence = broken_at_sequence
        self.increment_version()

    def mark_repairing(self) -> None:
        self.status = "repairing"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "stream_name": self.stream_name,
            "last_hash": self.last_hash,
            "last_sequence": self.last_sequence,
            "event_count": self.event_count,
            "genesis_hash": self.genesis_hash,
            "status": self.status,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "verified_by": str(self.verified_by) if self.verified_by else None,
            "broken_at_sequence": self.broken_at_sequence,
            "repair_history": self.repair_history,
        }


__all__ = ["HashChainTable"]