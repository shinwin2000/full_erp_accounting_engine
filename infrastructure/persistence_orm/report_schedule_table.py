#!/usr/bin/env python3
"""
Module: report_schedule_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk penjadwalan laporan (cron, next run, last run, recipient).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base


class ReportScheduleTable(Base):
    __tablename__ = "report_schedule"
    __table_args__ = (
        Index("idx_report_schedule_definition", "definition_id"),
        Index("idx_report_schedule_next_run", "next_run_at")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("report_definition.id"), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recipient_emails: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    definition: Mapped[ReportDefinitionTable] = relationship("ReportDefinitionTable")

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def update_last_run(self, last_run_at: datetime, next_run_at: datetime) -> None:
        self.last_run_at = last_run_at
        self.next_run_at = next_run_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "definition_id": str(self.definition_id),
            "cron_expression": self.cron_expression,
            "next_run_at": self.next_run_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "is_active": self.is_active,
            "recipient_emails": self.recipient_emails,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
        }


__all__ = ["ReportScheduleTable"]
