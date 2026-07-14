#!/usr/bin/env python3
"""
Module: event_store_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel event_store.
               Tabel ini adalah heart dari event sourcing architecture.
               Semua event yang terjadi di sistem disimpan di sini secara
               append-only. Data tidak dapat diubah atau dihapus setelah ditulis.
               Setiap event memiliki hash yang terkait dengan event sebelumnya
               untuk menjamin integritas rantai (hash chain).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- sqlalchemy.dialects.postgresql (UUID, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin)
Audit: Tabel ini bersifat immutable. Trigger PostgreSQL mencegah UPDATE/DELETE.
       Hash chain diverifikasi secara periodik oleh tamper detection scanner.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class EventStoreTable(Base, TimestampMixin, SoftDeleteMixin):
    """
    Model untuk tabel event_store.
    Tabel ini bersifat append-only (tidak ada UPDATE/DELETE setelah INSERT).
    """

    __tablename__ = "event_store"
    __table_args__ = (
        UniqueConstraint("stream_name", "sequence_number", name="uq_event_store_stream_sequence"),
        CheckConstraint("stream_name IS NOT NULL AND stream_name != ''", name="ck_es_stream_name"),
        CheckConstraint("event_type IS NOT NULL AND event_type != ''", name="ck_es_event_type"),
        CheckConstraint("event_version >= 1", name="ck_es_event_version"),
        CheckConstraint("sequence_number >= 1", name="ck_es_sequence_number"),
        CheckConstraint("previous_hash IS NOT NULL", name="ck_es_previous_hash"),
        CheckConstraint("hash IS NOT NULL", name="ck_es_hash"),
        Index("idx_es_stream_name", "stream_name"),
        Index("idx_es_stream_sequence", "stream_name", "sequence_number"),
        Index("idx_es_event_type", "event_type"),
        Index("idx_es_timestamp", "timestamp"),
        Index("idx_es_legal_entity", "legal_entity_id"),
        Index("idx_es_aggregate_id", "aggregate_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    stream_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)

    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Event payload and metadata
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # NOTE: renamed from 'metadata' to avoid SQLAlchemy reserved attribute name
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timestamp when event occurred (from domain)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Hash chain fields
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Optional: reference to aggregate root
    aggregate_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Correlation and causation IDs for tracing
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Legal entity (for multi-tenant)
    legal_entity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # User who triggered the event (if applicable)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_genesis(self) -> bool:
        """Check if this is the first event in its stream."""
        return self.sequence_number == 1

    @property
    def stream_key(self) -> str:
        """Get the stream key (aggregate_type:aggregate_id)."""
        return self.stream_name

    @property
    def display_name(self) -> str:
        """Get human-readable event name."""
        return f"{self.event_type} v{self.event_version} [{self.sequence_number}]"

    # ========================================================================
    # METHODS
    # ========================================================================

    @classmethod
    def create_genesis(
        cls,
        stream_name: str,
        event_type: str,
        data: dict,
        metadata: dict | None = None,
        legal_entity_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> EventStoreTable:
        """
        Create a genesis event (first event in a stream).
        """
        genesis_hash = sha256(b"EVENT_STORE_GENESIS_2025").hexdigest()
        timestamp = datetime.now(UTC)

        # Compute hash for genesis event
        content = {
            "data": data,
            "metadata": metadata or {},
            "timestamp": timestamp.isoformat(),
            "previous_hash": genesis_hash,
        }
        content_hash = sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()

        return cls(
            stream_name=stream_name,
            sequence_number=1,
            event_type=event_type,
            event_version=1,
            data=data,
            event_metadata=metadata,
            timestamp=timestamp,
            previous_hash=genesis_hash,
            hash=content_hash,
            legal_entity_id=legal_entity_id,
            user_id=user_id,
        )

    def verify_hash(self) -> bool:
        """
        Verify that the event's hash matches its content.
        """
        content = {
            "data": self.data,
            "metadata": self.event_metadata,
            "timestamp": self.timestamp.isoformat(),
            "previous_hash": self.previous_hash,
        }
        computed_hash = sha256(
            json.dumps(content, sort_keys=True, default=str).encode()
        ).hexdigest()
        return computed_hash == self.hash

    def verify_chain_link(self, previous_event: EventStoreTable) -> bool:
        """
        Verify that this event correctly links to the previous event in the chain.
        """
        if self.sequence_number != previous_event.sequence_number + 1:
            return False
        if self.stream_name != previous_event.stream_name:
            return False
        if self.previous_hash != previous_event.hash:
            return False
        return self.verify_hash()


__all__ = ["EventStoreTable"]