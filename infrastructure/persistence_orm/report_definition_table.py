#!/usr/bin/env python3
"""
Module: report_definition_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk definisi report (query, parameter, template).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class ReportDefinitionTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "report_definition"
    __table_args__ = (
        Index("idx_report_def_code", "report_code", "legal_entity_id", unique=True),
        Index("idx_report_def_category", "category"),
        Index("idx_report_def_is_active", "is_active")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_code: Mapped[str] = mapped_column(String(50), nullable=False)
    report_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    query_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    template_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_formats: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def activate(self) -> None:
        self.is_active = True
        self.increment_version()

    def deactivate(self) -> None:
        self.is_active = False
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "report_code": self.report_code,
            "report_name": self.report_name,
            "description": self.description,
            "category": self.category,
            "query_sql": self.query_sql,
            "parameters_schema": self.parameters_schema,
            "template_path": self.template_path,
            "output_formats": self.output_formats,
            "is_active": self.is_active,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["ReportDefinitionTable"]
