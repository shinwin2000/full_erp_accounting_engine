#!/usr/bin/env python3
"""
Module: coretax_submission_log_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk mencatat log submission ke Coretax DJP.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base


class CoretaxSubmissionLogTable(Base):
    __tablename__ = "coretax_submission_log"
    __table_args__ = (
        Index("idx_coretax_log_submission_id", "submission_id"),
        Index("idx_coretax_log_spt_type", "spt_type"),
        Index("idx_coretax_log_npwp", "npwp"),
        Index("idx_coretax_log_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    spt_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    npwp: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "submission_id": str(self.submission_id) if self.submission_id else None,
            "spt_type": self.spt_type,
            "npwp": self.npwp,
            "action": self.action,
            "status": self.status,
            "request_payload": self.request_payload,
            "response_payload": self.response_payload,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
        }


__all__ = ["CoretaxSubmissionLogTable"]
