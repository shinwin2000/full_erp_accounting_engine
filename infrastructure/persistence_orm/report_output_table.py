#!/usr/bin/env python3
"""
Module: report_output_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan output report (file, metadata).
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base


class ReportOutputTable(Base):
    __tablename__ = "report_output"
    __table_args__ = (
        Index("idx_report_output_definition", "definition_id"),
        Index("idx_report_output_generated_at", "generated_at"),
        Index("idx_report_output_format", "output_format"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    output_format: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def mark_failed(self, error_message: str) -> None:
        self.status = "failed"
        self.error_message = error_message

    def mark_completed(self) -> None:
        self.status = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "definition_id": str(self.definition_id),
            "output_format": self.output_format,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "parameters": self.parameters,
            "generated_at": self.generated_at.isoformat(),
            "generated_by": str(self.generated_by) if self.generated_by else None,
            "status": self.status,
            "error_message": self.error_message,
        }


__all__ = ["ReportOutputTable"]