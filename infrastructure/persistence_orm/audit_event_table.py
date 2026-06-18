#!/usr/bin/env python3
"""
Module: audit_event_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel audit_event.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class AuditEventTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint("event_type IS NOT NULL AND event_type != ''", name="ck_ae_event_type"),
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')", name="ck_ae_severity"
        ),
        Index("idx_ae_event_type", "event_type"),
        Index("idx_ae_severity", "severity"),
        Index("idx_ae_user_id", "user_id"),
        Index("idx_ae_legal_entity", "legal_entity_id"),
        Index("idx_ae_timestamp", "timestamp"),
        Index("idx_ae_correlation_id", "correlation_id"),
        Index("idx_ae_aggregate", "aggregate_type", "aggregate_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_critical(self) -> bool:
        return self.severity == "CRITICAL"

    @property
    def is_error(self) -> bool:
        return self.severity == "ERROR"

    @classmethod
    def create(
        cls,
        event_type: str,
        action: str,
        user_id: uuid.UUID | None = None,
        username: str | None = None,
        ip_address: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        details: dict | None = None,
        severity: str = "INFO",
        legal_entity_id: uuid.UUID | None = None,
    ) -> AuditEventTable:
        return cls(
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
            details=details,
            legal_entity_id=legal_entity_id,
            timestamp=datetime.utcnow(),
        )

    @classmethod
    def create_critical(
        cls,
        event_type: str,
        action: str,
        error_message: str,
        user_id: uuid.UUID | None = None,
        **kwargs,
    ) -> AuditEventTable:
        return cls.create(
            event_type=event_type,
            action=action,
            user_id=user_id,
            error_message=error_message,
            severity="CRITICAL",
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "severity": self.severity,
            "user_id": str(self.user_id) if self.user_id else None,
            "username": self.username,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "details": self.details,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id) if self.aggregate_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


__all__ = ["AuditEventTable"]
